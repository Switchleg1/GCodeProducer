"""GCodeLine — gcode subsystem."""
from __future__ import annotations
import re
from typing import Optional
from gcodeproducer.core.gcode.gcode_constants import (
    _WORD_RE,
    _PAREN_RE,
    TEXT_COMMANDS,
    MOTION_COMMANDS,
    DECIMALS,
    _EMPTY,
)

class GCodeLine:
    """A single line of G-code.

    Attributes
    ----------
    raw      original text (no newline)
    cmd      normalised command ("G1", "M104", "T0") or None
    params   dict letter -> float
    comment  text after ';' (and parenthesised comments), or None
    extra    unparsed argument text for text commands (M117 ...)
    layer    0-based layer index assigned by the reader
    feature  canonical feature id assigned by the reader
    op       operation / group name (CAM: machining operation), or None
    engagement  CAM: radial tool engagement 0..1 of a cutting move (nan = n/a)
    origin   index of the line in the source file (None = inserted)
    note     description of the modification made by a module (None = untouched)
    """

    __slots__ = ("raw", "cmd", "params", "comment", "extra", "layer", "feature", "op", "engagement",
                 "origin", "note", "dirty", "_text")

    def __init__(self, raw: str = "", origin: Optional[int] = None):
        self.raw = raw
        self.cmd: Optional[str] = None
        self.params: dict = _EMPTY
        self.comment: Optional[str] = None
        self.extra: Optional[str] = None
        self.layer: int = 0
        self.feature: str = "unknown"
        self.op: Optional[str] = None
        self.engagement: float = float("nan")
        self.origin = origin
        self.note: Optional[str] = None
        self.dirty = False
        self._text: Optional[str] = None
        self._parse(raw)

    # ------------------------------------------------------------------ parse
    def _parse(self, raw: str) -> None:
        from gcodeproducer.core.gcode.parsing import _normalise_cmd
        code = raw
        idx = raw.find(";")
        if idx >= 0:
            self.comment = raw[idx + 1:]
            code = raw[:idx]
        if "(" in code:
            parts = _PAREN_RE.findall(code)
            if parts:
                pc = " ".join(p.strip() for p in parts)
                self.comment = pc if self.comment is None else pc + " " + self.comment
                code = _PAREN_RE.sub(" ", code)
        code = code.strip()
        if not code:
            return
        if code[0] in "Nn":  # strip line number
            m = re.match(r"[Nn]\d+\s*", code)
            if m:
                code = code[m.end():]
        star = code.find("*")
        if star >= 0:
            code = code[:star]
        m = _WORD_RE.match(code)
        if m and m.group(1).upper() in "GMT":
            self.cmd = _normalise_cmd(m.group(1), m.group(2))
            rest = code[m.end():]
            if self.cmd in TEXT_COMMANDS:
                self.extra = rest.strip()
                return
        else:
            rest = code
        words = _WORD_RE.findall(rest)
        if words:
            params = {}
            extras = []
            for letter, num in words:
                letter = letter.upper()
                if letter in "GM" or letter in params:
                    extras.append(letter + num)
                    continue
                params[letter] = float(num)
            self.params = params
            if extras:
                self.extra = " ".join(extras)

    @classmethod
    def parsed(cls, raw: str, cmd: str, params: dict, origin: Optional[int] = None) -> "GCodeLine":
        """A line whose command and words are already known (``raw`` must parse to them)."""
        ln = cls.__new__(cls)
        ln.raw = raw
        ln.cmd = cmd
        ln.params = params
        ln.comment = None
        ln.extra = None
        ln.layer = 0
        ln.feature = "unknown"
        ln.op = None
        ln.engagement = float("nan")
        ln.origin = origin
        ln.note = None
        ln.dirty = False
        ln._text = None
        return ln

    @classmethod
    def make(cls, text: str, template: Optional["GCodeLine"] = None, note: Optional[str] = None) -> "GCodeLine":
        """Create a new (inserted) line, inheriting layer/feature from ``template``."""
        ln = cls(text, origin=None)
        if template is not None:
            ln.layer = template.layer
            ln.feature = template.feature
            ln.op = template.op
        ln.note = note
        return ln

    def clone(self) -> "GCodeLine":
        c = GCodeLine.__new__(GCodeLine)
        c.raw = self.raw
        c.cmd = self.cmd
        c.params = self.params if self.params is _EMPTY else dict(self.params)
        c.comment = self.comment
        c.extra = self.extra
        c.layer = self.layer
        c.feature = self.feature
        c.op = self.op
        c.engagement = self.engagement
        c.origin = self.origin
        c.note = self.note
        c.dirty = self.dirty
        c._text = self._text
        return c

    # ------------------------------------------------------------- accessors
    @property
    def is_motion(self) -> bool:
        return self.cmd in MOTION_COMMANDS

    @property
    def is_blank(self) -> bool:
        return self.cmd is None and not self.params and self.comment is None

    def has(self, letter: str) -> bool:
        return letter in self.params

    def get(self, letter: str, default=None):
        return self.params.get(letter, default)

    def set(self, letter: str, value: float, decimals: Optional[int] = None) -> None:
        if decimals is None:
            decimals = DECIMALS.get(letter, 4)
        value = round(float(value), decimals)
        if self.params is _EMPTY:
            self.params = {}
        if self.params.get(letter) == value:
            return
        self.params[letter] = value
        self.dirty = True
        self._text = None

    def remove(self, letter: str) -> None:
        if letter in self.params:
            del self.params[letter]
            self.dirty = True
            self._text = None

    def mark(self, note: str) -> None:
        """Attach a modification note (shown in the GUI change list)."""
        if self.note and note not in self.note:
            self.note = self.note + " | " + note
        else:
            self.note = note

    @property
    def is_changed(self) -> bool:
        return self.origin is None or self.dirty or self.note is not None

    @property
    def text(self) -> str:
        from gcodeproducer.core.gcode.parsing import format_number
        if not self.dirty:
            return self.raw
        if self._text is None:
            parts = []
            if self.cmd:
                parts.append(self.cmd)
            if self.extra:
                parts.append(self.extra)
            for k, v in self.params.items():
                parts.append(k + format_number(v))
            s = " ".join(parts)
            if self.comment is not None:
                s = (s + " ;" + self.comment) if s else ";" + self.comment
            self._text = s
        return self._text

    def __repr__(self) -> str:  # pragma: no cover
        return f"GCodeLine({self.text!r}, layer={self.layer}, feature={self.feature})"
