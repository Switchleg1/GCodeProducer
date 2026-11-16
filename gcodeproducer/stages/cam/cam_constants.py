"""Shared cam constants and declarative tables."""
from __future__ import annotations
import re

_LINE = re.compile(r"^Line (\d+):")

from gcodeproducer.stages.base.api import AUTO, Param

CAMEMIT_PARAMS = []

CAMPROFILE_PARAMS = [
        Param("side", "choice", "outside", group="Contour",
              choices=[("outside", "Outside the part"), ("inside", "Inside (pocket wall)"),
                       ("on", "On the line")]),
        Param("stock_to_leave", "float", 0.0, unit="mm", min=0, decimals=2, group="Contour"),
        Param("stepdown", "float", AUTO, unit="mm", min=0.01, decimals=2, allow_auto=True, hint=1.0,
              group="Depth", help="auto = tool max depth per pass."),
        Param("final_depth", "float", AUTO, unit="mm", min=0.01, decimals=2, allow_auto=True, hint=5.0,
              group="Depth", help="Depth below the top of the part; auto = through the whole part."),
    ]
