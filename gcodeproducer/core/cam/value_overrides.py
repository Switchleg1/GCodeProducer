"""Operation values that are not used as entered: capped by the tool or machine, or not used at all.

``operation_overrides`` returns ``{field: message}`` for the operation editor,
which shows each message as a warning on that field. Fields are operation
attribute names. Only what can be known from the operation, its tool, the
machine and the stock is reported; caps that depend on the geometry (the
overcut kept inside the material boundary, for example) are not.
"""
from __future__ import annotations
import math

from .cam_constants import FEED_FIELDS, PLUNGE_FEED_FIELD
from .cutting import resolve_cutting
from .strategy import cutting_strategy


def operation_overrides(machine, tool, stock, op):
    messages = {}
    data = resolve_cutting(machine, tool, stock, op)
    if data.requested_stepdown > data.stepdown+1e-9:
        messages["stepdown"] = (f"Capped by the tool: this operation asks for {data.requested_stepdown:g} mm per pass, "
                                f"but the tool's Max depth/pass is {data.stepdown:g} mm, so passes are "
                                f"{data.stepdown:g} mm deep. Raise or clear (0) Max depth/pass in the tool library "
                                f"to cut deeper.")
    if data.requested_rpm >= data.rpm+1:
        messages["rpm"] = (f"Capped: {data.requested_rpm:.0f} rpm asked for, but the spindle runs at most "
                           f"{data.rpm:.0f} rpm ({data.rpm_limit_source}).")
    top = float(machine.get("max_feed", 0) or 0) if machine is not None else 0.
    if top > 0 and math.isfinite(top):
        names = {"feed": "cut base feed", "lead_feed": "lead-in base feed", "plunge_feed": "plunge feed"}
        for field, value in (("feed", data.feed), ("lead_feed", data.lead_feed), ("plunge_feed", data.plunge)):
            if value > top+1e-9:
                messages[field] = (f"Capped by the machine: the {names[field]} is {value:g} mm/min, but the machine's "
                                   f"Max feed is {top:g} mm/min, so those moves run at {top:g} mm/min.")
        resolved = machine.resolved() if hasattr(machine, "resolved") else machine
        for regime, (field, default) in FEED_FIELDS.items():
            own = float(getattr(op, field, 0) or 0)
            percent = own or float((resolved.get(field, default) if regime in ("slot", "high")
                                    else tool.get(field, default)))
            rate = data.feed*percent/100
            if rate > top+1e-9 and field not in messages:
                messages[field] = (f"Capped by the machine: {percent:g} % of the {data.feed:g} mm/min cut feed is "
                                   f"{rate:g} mm/min, above the machine's Max feed of {top:g} mm/min, so these "
                                   f"moves run at {top:g} mm/min.")
    if op.unlock_lead_feed and float(getattr(op, "lead_in_feed_modifier", 0) or 0) > 0:
        messages["lead_in_feed_modifier"] = ("Not used: the lead-in base feed is unlocked, so it is the lead-in feed "
                                             "whatever this percentage says.")
    field = PLUNGE_FEED_FIELD[0]
    if getattr(op, "unlock_plunge_feed", False) and float(getattr(op, field, 0) or 0) > 0:
        messages[field] = ("Not used: the plunge feed is unlocked, so it is the plunge feed whatever this "
                           "percentage says.")
    if op.kind in ("pocket", "waterfall") and cutting_strategy(op.kind, op.strategy) == "contour" and op.stepover > 50:
        messages["stepover"] = (f"Capped: wall-parallel contours are at most 50 % of the cutter apart (so the "
                                f"offset fronts still cover where they meet); {op.stepover:g} % is used as 50 %.")
    return messages


def tool_overrides(values, machine):
    """A tool's fixed rates above what the machine allows, and its reach (the tool library editor)."""
    messages = {}
    flute, stickout = float(values.get("length", 0) or 0), float(values.get("stickout", 0) or 0)
    if stickout <= 0:
        messages["stickout"] = ("Not set: how deep this tool may reach before the collet meets the stock is not "
                                "checked. Measure from the collet face to the tip.")
    elif flute > stickout+1e-9:
        messages["stickout"] = (f"Shorter than the flute length ({flute:g} mm): the collet would grip the flutes. "
                                f"Check both lengths.")
    if machine is None:
        return messages
    if not values.get("auto_cutting_data", False):
        rpm, limits = float(values.get("spindle_rpm", 0) or 0), []
        for key, which in (("spindle_max", "machine's Spindle max"),):
            limit = float(machine.get(key, 0) or 0)
            if limit > 0:
                limits.append((limit, which))
        own = float(values.get("max_spindle_rpm", 0) or 0)
        if own > 0:
            limits.append((own, "tool's Max spindle RPM"))
        if limits:
            limit, which = min(limits)
            if rpm > limit+1e-9:
                messages["spindle_rpm"] = (f"Capped: {rpm:g} rpm, but the {which} is {limit:g} rpm, "
                                           f"so the spindle runs at {limit:g} rpm.")
        top = float(machine.get("max_feed", 0) or 0)
        if top > 0:
            for name, label in (("feed", "cut feed"), ("plunge_feed", "lead-in feed")):
                value = float(values.get(name, 0) or 0)
                if value > top+1e-9:
                    messages[name] = (f"Capped by the machine: a {label} of {value:g} mm/min, but the machine's "
                                      f"Max feed is {top:g} mm/min.")
    return messages

