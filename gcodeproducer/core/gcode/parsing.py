"""G-code line / program model.

Lines keep their original text (``raw``) and are only re-generated when a
module modifies them, so untouched lines are written back byte-for-byte.
"""
from __future__ import annotations

from gcodeproducer.core.gcode.line import GCodeLine
from gcodeproducer.core.gcode.program import GCodeProgram
from gcodeproducer.core.gcode.gcode_constants import (
    _WORD_RE,
    _PAREN_RE,
    TEXT_COMMANDS,
    MOTION_COMMANDS,
    DECIMALS,
    _EMPTY,
)


# A G-code word: letter followed by a number (no exponent, 'E' is an axis).

# Commands whose arguments are free text and must never be tokenised.


# Default number of decimals used when a module sets a value.


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
