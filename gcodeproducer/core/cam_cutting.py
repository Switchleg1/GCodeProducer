"""Machining-material/tool cutting data, distinct from FDM filament profiles.

SFM is ft/min; diameter/chip load are mm and mm/tooth. Starter numbers are
illustrative, NOT manufacturer-qualified machining recommendations.
"""
from dataclasses import dataclass
import math

MATERIALS = (
    ("soft_wood", "Soft wood", 600., .05),
    ("hard_wood", "Hard wood", 400., .04),
    ("soft_plastic", "Soft plastic", 300., .03),
    ("hard_plastic", "Hard plastic", 200., .02),
    ("non_iron_metal", "Non-iron metal", 300., .03),
    ("steel", "Steel", 80., .015),
)
MATERIAL_KEYS = {m[0] for m in MATERIALS}


def material_parameters():
    from .params import Param
    params = [Param("auto_cutting_data", "bool", False, label="Calculate from SFM / chip load",
                    group="Cutting calculation", help="Enable after calibrating the per-material data. Legacy tools retain fixed feeds/RPM."),
              Param("max_spindle_rpm", "float", 24000., min=1, unit="rpm", group="Cutting calculation",
                    help="Tool RPM ceiling, also respected for manual RPM requests."),
              Param("lead_feed_percent", "float", 35., min=1, max=100, unit="%", group="Cutting calculation",
                    help="Automatic lead/plunge feed as a percentage of calculated normal feed.")]
    for key, label, sfm, chip in MATERIALS:
        group = f"Cut data: {label}"
        params += [Param(f"{key}_sfm", "float", sfm, min=.1, unit="ft/min", group=group, label="SFM"),
                   Param(f"{key}_chip_load", "float", chip, min=.0001, unit="mm/tooth", decimals=4,
                         group=group, label="Chip load")]
        for process, percent in (("slot",15.),("pocket",25.),("profile",40.)):
            params.append(Param(f"{key}_{process}_axial", "float", percent, min=1, max=200,
                                unit="% D", group=group, label=f"{process.title()} axial depth",
                                help=f"Automatic {process} stepdown for {label} only (choose the machining category in Material / stock). "
                                     "Percentage of tool diameter, capped by Max depth/pass; the operation depth override takes precedence."))
    return params


@dataclass
class CuttingData:
    rpm: float
    feed: float
    lead_feed: float
    stepdown: float
    material: str
    depth_source: str = ""
    requested_stepdown: float = 0.0

    def summary(self):
        label = next((m[1] for m in MATERIALS if m[0] == self.material), self.material)
        source = f" • {self.depth_source}" if self.depth_source else ""
        cap = f" (capped from {self.requested_stepdown:.3f})" if self.requested_stepdown > self.stepdown+1e-9 else ""
        return (f"{label}{source} • {self.rpm:.0f} rpm • requested cut {self.feed:g} • lead {self.lead_feed:g} mm/min "
                f"• depth/pass {self.stepdown:.3f} mm{cap}")


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
    lead = feed*float(tool.get("lead_feed_percent",35))/100 if automatic else float(tool.get("plunge_feed",300))
    if operation is not None and operation.unlock_feed:
        feed = float(operation.feed)
    if operation is not None and operation.unlock_lead_feed:
        lead = float(operation.lead_feed)
    for value in (feed,lead):
        if value <= 0 or not math.isfinite(value):
            raise ValueError("Cut and lead/plunge feeds must be positive and finite")
    kind = getattr(operation,"kind","profile")
    axial_kind = kind if kind in ("slot","pocket","profile") else "slot"
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
    return CuttingData(rpm,feed,lead,step,key,depth_source,requested_stepdown)
