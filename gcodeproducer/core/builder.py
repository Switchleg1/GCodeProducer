"""G-code emitter.

Where GCodeTools *reads* G-code into a :class:`GCodeProgram`, GCodeProducer
*writes* one.  :class:`GCodeBuilder` tracks machine state (position, modal feed,
extruder, units, active feature / layer) and appends fully-formed
:class:`~gcodeproducer.core.gcode.GCodeLine` objects, so the produced program
can be fed straight into the same 3D viewer and simulation the tools app uses.
"""
from __future__ import annotations

import math
from typing import Optional

from .gcode import GCodeLine, GCodeProgram, format_number


class GCodeBuilder:
    def __init__(self, relative_e: bool = True, decimals_xyz: int = 3, decimals_e: int = 5):
        self.lines: list[GCodeLine] = []
        self.relative_e = relative_e
        self.dx, self.de = decimals_xyz, decimals_e
        self.x = self.y = self.z = 0.0
        self.e = 0.0
        self.feed: Optional[float] = None      # mm/min
        self.layer = 0
        self.feature = "unknown"
        self.op: Optional[str] = None
        self._origin = 0

    # ---------------------------------------------------------- low level
    def _emit(self, text: str, comment: Optional[str] = None) -> GCodeLine:
        raw = text if comment is None else (f"{text} ;{comment}" if text else f";{comment}")
        ln = GCodeLine(raw, origin=self._origin)
        self._origin += 1
        ln.layer = self.layer
        ln.feature = self.feature
        ln.op = self.op
        self.lines.append(ln)
        return ln

    def comment(self, text: str) -> GCodeLine:
        return self._emit("", text)

    def blank(self) -> GCodeLine:
        return self._emit("")

    def raw(self, text: str) -> None:
        """Emit possibly-multiline literal G-code (start/end blocks)."""
        for row in str(text).splitlines():
            self._emit(row.rstrip())

    def command(self, text: str, comment: Optional[str] = None) -> GCodeLine:
        return self._emit(text, comment)

    # ------------------------------------------------------------ context
    def set_feature(self, feature: str, comment: bool = True) -> None:
        if feature != self.feature:
            self.feature = feature
            if comment:
                self._emit("", f"TYPE:{feature}")

    def new_layer(self, index: int, z: float, comment: bool = True) -> None:
        self.layer = index
        if comment:
            self._emit("", f"LAYER:{index}")
        self.move_z(z)

    # ------------------------------------------------------------- motion
    @staticmethod
    def _fmt(letter: str, value: float, dec: int) -> str:
        return letter + format_number(value, dec)

    def _xyzf(self, x=None, y=None, z=None, f=None) -> str:
        parts = []
        if x is not None and abs(x - self.x) > 10 ** -self.dx:
            parts.append(self._fmt("X", x, self.dx)); self.x = x
        elif x is not None:
            self.x = x
        if y is not None and abs(y - self.y) > 10 ** -self.dx:
            parts.append(self._fmt("Y", y, self.dx)); self.y = y
        elif y is not None:
            self.y = y
        if z is not None and abs(z - self.z) > 10 ** -self.dx:
            parts.append(self._fmt("Z", z, self.dx)); self.z = z
        elif z is not None:
            self.z = z
        if f is not None and f != self.feed:
            parts.append(self._fmt("F", f, 1)); self.feed = f
        return " ".join(parts)

    def move_z(self, z: float, feed: Optional[float] = None) -> None:
        body = self._xyzf(z=z, f=feed)
        if body:
            self._emit("G1 " + body if feed else "G0 " + body)

    def travel(self, x: float, y: float, z: Optional[float] = None, feed: Optional[float] = None) -> None:
        body = self._xyzf(x=x, y=y, z=z, f=feed)
        if body:
            self._emit("G0 " + body)

    def extrude_to(self, x: float, y: float, e_per_mm: float,
                   z: Optional[float] = None, feed: Optional[float] = None) -> None:
        """Print a straight segment to (x, y), depositing ``e_per_mm`` mm of filament per mm travelled."""
        dist = math.hypot(x - self.x, y - self.y)
        if z is not None:
            dist = math.hypot(dist, z - self.z)
        de = e_per_mm * dist
        body = self._xyzf(x=x, y=y, z=z, f=feed)
        if not body and de == 0:
            return
        if self.relative_e:
            eword = self._fmt("E", de, self.de)
            self.e += de
        else:
            self.e += de
            eword = self._fmt("E", self.e, self.de)
        self._emit(f"G1 {body} {eword}".replace("  ", " ").strip())

    def retract(self, length: float, speed_mm_s: float, zhop: float = 0.0) -> None:
        if length <= 0:
            return
        f = speed_mm_s * 60.0
        if self.relative_e:
            self._emit(f"G1 F{format_number(f,1)} E{format_number(-length,self.de)}", "retract")
            self.e -= length
        else:
            self.e -= length
            self._emit(f"G1 F{format_number(f,1)} E{format_number(self.e,self.de)}", "retract")
        self.feed = f
        if zhop > 0:
            self.move_z(self.z + zhop)

    def unretract(self, length: float, speed_mm_s: float, zhop: float = 0.0) -> None:
        if zhop > 0:
            self.move_z(self.z - zhop)
        if length <= 0:
            return
        f = speed_mm_s * 60.0
        if self.relative_e:
            self._emit(f"G1 F{format_number(f,1)} E{format_number(length,self.de)}", "unretract")
            self.e += length
        else:
            self.e += length
            self._emit(f"G1 F{format_number(f,1)} E{format_number(self.e,self.de)}", "unretract")
        self.feed = f

    def reset_e(self) -> None:
        if not self.relative_e:
            self._emit("G92 E0")
        self.e = 0.0

    # ---------------------------------------------------------- finalise
    def program(self, path: Optional[str] = None) -> GCodeProgram:
        prog = GCodeProgram(self.lines, path)
        prog.machine = "fdm"
        if self.lines:
            prog.layer_z = []
        return prog


def extrusion_per_mm(line_width: float, layer_height: float, filament_diameter: float,
                     flow: float = 1.0) -> float:
    """mm of filament consumed per mm of travel for a rounded-rectangle bead."""
    # bead cross-section: rectangle + two half-circles (PrusaSlicer model)
    w, h = line_width, layer_height
    area = (w - h) * h + math.pi * (h / 2) ** 2 if w >= h else math.pi * (w / 2) ** 2
    fil_area = math.pi * (filament_diameter / 2) ** 2
    return (area / fil_area) * flow
