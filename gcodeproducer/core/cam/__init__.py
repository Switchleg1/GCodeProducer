"""Compatibility exports. Implementation: gcodeproducer.core.cam.planning."""
from gcodeproducer.core.cam.stock import Stock
from gcodeproducer.core.cam.holding_tab import HoldingTab
from gcodeproducer.core.cam.cam_constants import KINDS
from gcodeproducer.core.cam.reference import Reference
from gcodeproducer.core.cam.depth import Depth
from gcodeproducer.core.cam.operation import Operation
from gcodeproducer.core.cam.tool_group import ToolGroup
from gcodeproducer.core.cam.cam_setup import CAMSetup
from gcodeproducer.core.cam.planning import (
    fingerprint,
    chains,
    pick_geometry,
    _cached,
    cached_topology,
    highlight_geometry,
    _drop_air_paths,
    _tab_schedule,
    generate,
)
from gcodeproducer.core.cam.topology import Topology
