"""GCodeProgram — gcode subsystem."""
from __future__ import annotations
from typing import Iterator, Optional
from gcodeproducer.core.gcode.line import GCodeLine

class GCodeProgram:
    """A complete G-code file."""

    def __init__(self, lines: Optional[list] = None, path: Optional[str] = None):
        self.lines: list[GCodeLine] = lines if lines is not None else []
        self.path = path
        self.newline = "\n"
        self.trailing_newline = True
        self.reader_id: Optional[str] = None
        self.reader_name: str = ""
        self.machine: str = "fdm"           # core.machines.FDM (3D printing) or CAM (machining)
        self.settings: dict = {}            # raw slicer/CAM settings
        self.slicer: dict = {}              # normalised settings (see readers.base)
        self.layer_z: list = []             # Z height per layer index
        self.parts: list = []               # (first line, label) per separate output file; [] = one file
        self.motion: dict = {}              # FDM firmware motion settings for the time estimate

    # ------------------------------------------------------------ creation
    @classmethod
    def from_text(cls, text: str, path: Optional[str] = None) -> "GCodeProgram":
        newline = "\r\n" if "\r\n" in text[:10000] else "\n"
        trailing = text.endswith("\n")
        rows = text.splitlines()
        prog = cls([GCodeLine(r, i) for i, r in enumerate(rows)], path)
        prog.newline = newline
        prog.trailing_newline = trailing
        return prog

    @classmethod
    def from_file(cls, path: str) -> "GCodeProgram":
        with open(path, "r", encoding="utf-8", errors="replace", newline="") as fh:
            text = fh.read()
        return cls.from_text(text, path)

    def clone(self) -> "GCodeProgram":
        p = GCodeProgram([ln.clone() for ln in self.lines], self.path)
        p.newline = self.newline
        p.trailing_newline = self.trailing_newline
        p.reader_id = self.reader_id
        p.reader_name = self.reader_name
        p.machine = self.machine
        p.settings = dict(self.settings)
        p.slicer = dict(self.slicer)
        p.layer_z = list(self.layer_z)
        p.parts = list(self.parts)
        p.motion = dict(getattr(self, "motion", {}) or {})
        return p

    # -------------------------------------------------------------- output
    def iter_text(self) -> Iterator[str]:
        for ln in self.lines:
            yield ln.text

    def to_text(self) -> str:
        s = self.newline.join(self.iter_text())
        if self.trailing_newline:
            s += self.newline
        return s

    def save(self, path: str) -> list:
        """Write the program; a split program writes one numbered file per part. Returns the paths."""
        if not self.parts:
            with open(path, "w", encoding="utf-8", newline="") as fh:
                fh.write(self.to_text())
            return [path]
        from gcodeproducer.core.gcode.program_parts import part_path
        written = []
        ends = [start for start, _ in self.parts[1:]] + [len(self.lines)]
        for index, ((start, label), end) in enumerate(zip(self.parts, ends), 1):
            target = part_path(path, index, label)
            text = self.newline.join(line.text for line in self.lines[start:end])
            with open(target, "w", encoding="utf-8", newline="") as fh:
                fh.write(text + (self.newline if self.trailing_newline else ""))
            written.append(target)
        return written

    # --------------------------------------------------------------- query
    def __len__(self) -> int:
        return len(self.lines)

    @property
    def num_layers(self) -> int:
        if not self.lines:
            return 0
        return max(ln.layer for ln in self.lines) + 1

    def changed_lines(self) -> list[int]:
        return [i for i, ln in enumerate(self.lines) if ln.is_changed]

    def features(self) -> list[str]:
        seen = {}
        for ln in self.lines:
            seen.setdefault(ln.feature, None)
        return list(seen)
