"""G-code line / program model.

Lines keep their original text (``raw``) and are only re-generated when a
module modifies them, so untouched lines are written back byte-for-byte.
"""
from __future__ import annotations

import re
from typing import Iterable, Iterator, Optional

# A G-code word: letter followed by a number (no exponent, 'E' is an axis).
_WORD_RE = re.compile(r"([A-Za-z])\s*([-+]?(?:\d+\.?\d*|\.\d+))")
_PAREN_RE = re.compile(r"\(([^)]*)\)")

# Commands whose arguments are free text and must never be tokenised.
TEXT_COMMANDS = {"M117", "M118", "M23", "M28", "M29", "M30", "M32", "M928", "M587", "M588", "M550", "M551", "M552"}

MOTION_COMMANDS = {"G0", "G1", "G2", "G3"}

# Default number of decimals used when a module sets a value.
DECIMALS = {"X": 3, "Y": 3, "Z": 3, "E": 5, "F": 1, "I": 4, "J": 4, "K": 4, "R": 4, "S": 2, "P": 2}


def format_number(value: float, decimals: int = 6) -> str:
    if value == int(value) and abs(value) < 1e15:
        return str(int(value))
    s = f"{value:.{decimals}f}".rstrip("0").rstrip(".")
    if s in ("-0", ""):
        s = "0"
    return s


def _normalise_cmd(letter: str, num: str) -> str:
    letter = letter.upper()
    if "." in num:
        whole, frac = num.split(".", 1)
        whole = str(int(whole)) if whole.strip("+-") else "0"
        frac = frac.rstrip("0")
        return f"{letter}{whole}.{frac}" if frac else f"{letter}{whole}"
    return f"{letter}{int(num)}"


_EMPTY: dict = {}


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

    def save(self, path: str) -> None:
        with open(path, "w", encoding="utf-8", newline="") as fh:
            fh.write(self.to_text())

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


def parse_lines(rows: Iterable[str]) -> list[GCodeLine]:
    return [GCodeLine(r, i) for i, r in enumerate(rows)]
