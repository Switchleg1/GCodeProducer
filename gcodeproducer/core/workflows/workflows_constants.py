"""Shared workflows constants and declarative tables."""
from __future__ import annotations

FDM = "fdm"

CAM = "cam"

ALL = (FDM, CAM)

LABELS = {FDM: "FDM (3D printing)", CAM: "CAM (machining)"}

SHORT = {FDM: "FDM", CAM: "CAM"}

LIBRARIES = {
    FDM: ("machine", "material", "nozzle"),
    CAM: ("machine", "tool"),
}

_ALIASES = {
    "fdm": FDM, "fff": FDM, "fff/fdm": FDM, "printer": FDM, "3dp": FDM, "print": FDM,
    "cam": CAM, "cnc": CAM, "mill": CAM, "milling": CAM, "router": CAM, "machining": CAM,
}
