"""Machining-material/tool cutting data, distinct from FDM filament profiles.

SFM is ft/min; diameter/chip load are mm and mm/tooth. Starter numbers are
illustrative, NOT manufacturer-qualified machining recommendations.
"""

from gcodeproducer.core.cam.cutting_data import CuttingData
from gcodeproducer.core.cam.cam_constants import MATERIALS, MATERIAL_KEYS, PLUNGE_FEED_FIELD
import math


def resolve_cutting(machine, tool, stock=None, operation=None):
    key = getattr(stock, "category", "soft_wood")
    if key not in MATERIAL_KEYS:
        raise ValueError(f"Unknown machining material '{key}'")
    diameter = float(tool.get("diameter", 0))
    if diameter <= 0 or not math.isfinite(diameter):
        raise ValueError("Tool diameter must be positive")
    automatic = bool(tool.get("auto_cutting_data", False))
    rpm = float(tool.get("spindle_rpm", 18000))
    if automatic:
        rpm = float(tool.get(f"{key}_sfm"))*304.8/(math.pi*diameter)
    if operation is not None and operation.unlock_rpm:
        rpm = float(operation.rpm)
    caps=(float(machine.get("spindle_max",24000)),float(tool.get("max_spindle_rpm",24000)))
    if not math.isfinite(rpm) or rpm<=0 or any(not math.isfinite(c) or c<=0 for c in caps):
        raise ValueError("RPM request and machine/tool ceilings must be positive and finite")
    max_rpm = min(caps)
    requested_rpm = rpm
    limit_source = "machine Spindle max" if caps[0] <= caps[1] else "tool Max spindle RPM"
    rpm = math.floor(min(rpm, max_rpm))  # highest whole RPM within all ceilings, never round above SFM
    minimum = float(machine.get("spindle_min",0) or 0)
    if not math.isfinite(minimum) or minimum<0:
        raise ValueError("Machine minimum RPM must be nonnegative and finite")
    if rpm < minimum:
        raise ValueError(f"Requested/SFM tool RPM {rpm:.0f} is below machine minimum {minimum:g}; do not silently overspeed the material")
    if rpm <= 0 or not math.isfinite(rpm):
        raise ValueError("Spindle RPM must be positive and finite")
    feed = float(tool.get("feed",800))
    if automatic:
        feed = float(tool.get(f"{key}_chip_load"))*int(tool.get("flutes",2))*rpm
    # Calculated first (tool / machine defaults, then the operation's engagement-feed
    # percentages of the tool feed); the operation's unlocked feeds then override them.
    lead = feed*float(tool.get("lead_feed_percent",35))/100 if automatic else float(tool.get("plunge_feed",300))
    field, default = PLUNGE_FEED_FIELD
    percent = float(machine.get(field, default) if machine is not None else default)
    if operation is not None and float(getattr(operation, "lead_in_feed_modifier", 0) or 0) > 0:
        lead = feed*float(operation.lead_in_feed_modifier)/100
    if operation is not None and float(getattr(operation, field, 0) or 0) > 0:
        percent = float(getattr(operation, field))
    plunge = feed*percent/100
    if operation is not None and operation.unlock_feed:
        feed = float(operation.feed)
    if operation is not None and operation.unlock_lead_feed:
        lead = float(operation.lead_feed)
    if operation is not None and getattr(operation, "unlock_plunge_feed", False):
        plunge = float(operation.plunge_feed)
    for value in (feed,lead,plunge):
        if value <= 0 or not math.isfinite(value):
            raise ValueError("Cut, lead-in and plunge feeds must be positive and finite")
    kind = getattr(operation,"kind","profile")
    axial_kind = "pocket" if kind == "waterfall" else kind if kind in ("slot","pocket","profile") else "slot"
    percent = float(tool.get(f"{key}_{axial_kind}_axial",15))
    step = diameter*percent/100
    depth_source = f"{axial_kind.title()} {percent:g}% D"
    if operation is not None and not operation.auto_stepdown:
        step = float(operation.stepdown)
        depth_source = "Operation depth override"
    requested_stepdown = step
    maximum = float(tool.get("max_doc",0) or 0)
    if not math.isfinite(maximum) or maximum<0:
        raise ValueError("Tool maximum depth/pass must be nonnegative and finite")
    if maximum > 0:
        step = min(step,maximum)
    if step <= 0 or not math.isfinite(step):
        raise ValueError("Depth per pass must be positive and finite")
    return CuttingData(rpm,feed,lead,step,key,depth_source,requested_stepdown,plunge,requested_rpm,limit_source)
