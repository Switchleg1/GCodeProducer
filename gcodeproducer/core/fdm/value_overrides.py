"""FDM settings that are not used as entered: capped by the machine, or ignored by it.

Each function returns ``{parameter: message}`` for the editor showing those
parameters, which shows each message as a warning on that field. Only caps
that follow from the setting and the machine are reported: the volumetric
flow cap depends on the layer and line width of each path and is reported in
the slicing log, not here.
"""
from __future__ import annotations
import math

from gcodeproducer.stages.fdm.fdm_constants import FDMEMIT_PARAMS


def _limit(machine, key):
    value = float(machine.get(key, 0) or 0) if machine is not None else 0.
    return value if value > 0 and math.isfinite(value) else None


def process_overrides(values, machine):
    """Print speeds above the machine's Max print speed, travel above its Max travel speed, acceleration."""
    messages = {}
    top, travel = _limit(machine, "max_print_speed"), _limit(machine, "max_travel_speed")
    speeds = [p.name for p in FDMEMIT_PARAMS if p.unit == "mm/s" and p.name.endswith("_speed")]
    for name in speeds:
        value = values.get(name)
        if value is None:
            continue
        limit, which = (travel, "Max travel speed") if name == "travel_speed" else (top, "Max print speed")
        if limit is not None and float(value) > limit+1e-9:
            messages[name] = (f"Capped by the machine: {float(value):g} mm/s asked for, but the machine's {which} "
                              f"is {limit:g} mm/s, so these moves run at {limit:g} mm/s.")
    accel, most = values.get("acceleration"), _limit(machine, "max_acceleration")
    if accel and most is not None and float(accel) > most+1e-9:
        messages["acceleration"] = (f"Capped by the machine: {float(accel):g} mm/s² asked for, but the machine's "
                                    f"Max acceleration is {most:g} mm/s².")
    return messages


def material_overrides(values, machine):
    """Temperatures above the machine's limits; a chamber temperature on a machine without a heated chamber."""
    messages = {}
    for names, key, which in ((("temp_nozzle", "temp_nozzle_first"), "max_nozzle_temp", "Max nozzle temperature"),
                              (("temp_bed", "temp_bed_first"), "max_bed_temp", "Max bed temperature")):
        limit = _limit(machine, key)
        for name in names:
            value = values.get(name)
            if value is not None and limit is not None and float(value) > limit+1e-9:
                messages[name] = (f"Capped by the machine: {float(value):g} °C asked for, but the machine's {which} "
                                  f"is {limit:g} °C, so it heats to {limit:g} °C.")
    chamber = float(values.get("temp_chamber", 0) or 0)
    if chamber > 0 and machine is not None:
        if not machine.get("heated_chamber", False):
            messages["temp_chamber"] = "Ignored: the machine has no heated chamber."
        else:
            limit = _limit(machine, "max_chamber_temp")
            if limit is not None and chamber > limit+1e-9:
                messages["temp_chamber"] = (f"Capped by the machine: {chamber:g} °C asked for, but the machine's Max "
                                            f"chamber temperature is {limit:g} °C.")
    return messages
