"""CAM stage: emit G-code from the milling toolpaths.

Safe Z for start-up / tool changes, otherwise stay-down links or short retracts
above the current material, contour lead-in ramps, engagement-adjusted cutting
feeds and spindle control. Rates come from the tool (fixed or SFM / chip-load
calculated per machining material) and operation unlocks; safe Z, XY rapid,
feed caps and engagement thresholds from the machine; lead and retract
clearances from the global settings.
"""
from __future__ import annotations

from gcodeproducer.stages.cam.cam_constants import CAMEMIT_PARAMS, _LINE
import math, numpy as np
from gcodeproducer.core.cam.cam_constants import RAMP_TAN
from gcodeproducer.core.gcode.builder import GCodeBuilder
from gcodeproducer.core.gcode.parsing import format_number
from gcodeproducer.stages.base.api import CAM
from gcodeproducer.stages.base.slice_stage import SliceStage


def mark_collisions(program, warnings):
    """Recolour moves named by 'Line N:' findings as the Collision feature.

    Only line-specific findings are mapped; setup-level findings (unallocated
    stock, safe Z, part containment) have no single move to highlight.
    """
    count = 0
    for warning in warnings:
        m = _LINE.match(warning)
        if not m:
            continue
        index = int(m.group(1))-1
        if 0 <= index < len(program.lines) and program.lines[index].feature != "collision":
            program.lines[index].feature = "collision"
            count += 1
    return count


class CAMEmit(SliceStage):
    id = "cam_emit"
    name = "Output"
    description = "Turn the milling toolpaths into G-code with rapids, plunges and spindle control."
    workflows = (CAM,)
    optional = False
    category = "Output"
    params = CAMEMIT_PARAMS

    def run(self, job, params, ctx):
        b = GCodeBuilder(relative_e=False)
        b.e = 0.0
        tool_map = {t.id: t for t in job.tools}
        first_id = getattr(job.layers[0], "cam_tool_id", None) if job.layers else None
        tool = tool_map.get(first_id) or (job.tools[0] if job.tools else None)
        from gcodeproducer.core.cam.cutting import resolve_cutting
        from gcodeproducer.core.cam.material import height_stock_for
        from gcodeproducer.core.cam.material import simulate_material
        from gcodeproducer.core.settings.preferences import pref
        stock = getattr(job.cam_setup,"stock",None)
        if stock is None and job.settings.get("machining_material"):
            from gcodeproducer.core.cam.stock import Stock
            stock=Stock(category=job.settings["machining_material"])
        if stock is None and any(t.get("auto_cutting_data",False) for t in job.tools):
            raise ValueError("Automatic CAM tools need a machining material category (CLI: --cam-material)")
        live = height_stock_for(job,stock) if stock is not None and stock.allocated else None
        first_op = getattr(job.layers[0],"cam_operation_config",None) if job.layers else None
        first_data = resolve_cutting(job.machine,tool,stock,first_op) if tool else None
        position = np.zeros(3)
        active_radius=float(tool.get("diameter",0))/2 if tool else 0.
        safe_z = job.m("safe_z", 15.0)
        feed = tool.get("feed", 800) if tool else job.m("max_feed", 800)
        plunge = tool.get("plunge_feed", 300) if tool else 300
        rpm = first_data.rpm if first_data else (tool.get("spindle_rpm",18000) if tool else job.m("spindle_max",18000))
        rapid_xy = job.m("rapid_xy", 3000)
        from collections import Counter
        from gcodeproducer.core.cam.planner import (MotionSegment, MotionPlan, FeedPolicy,
                                                    EntryExitPlanner, LinkPlanner)
        from gcodeproducer.core.cam.surface_engagement import condition as measure, split_move
        from gcodeproducer.core.cam.engagement import engagement_band
        from gcodeproducer.core.cam.cam_constants import SURFACE_MAX_POINTS
        policy = FeedPolicy(job.m("max_feed", 0), pref(job, "highlight_conflicts"))
        plan = MotionPlan()
        job.motion_plan = plan
        lead_kinds = {}
        short_retracts = bool(pref(job,"short_retracts"))
        lead_clearance = max(.05, float(pref(job,"lead_clearance")))
        travel_clearance = max(.1, float(pref(job,"retract_clearance")))
        short_count = [0]
        stay_count = [0]
        surface_totals = Counter()
        surface_state = [live]
        samples = [0]
        machine_values = job.machine.resolved()
        engagement_band(.5, machine_values)   # validate thresholds even for an all-air program
        last_feed = None
        last_condition = None
        entries = links = None
        tool_values = tool.resolved() if tool else {}
        config = None
        name = None

        def feed_text(value):
            return format_number(value,4 if value<1 else 1)

        def rapid_z(z, comment=None):
            nonlocal position
            z = float(format_number(z, 3))
            b.set_feature("rapid", comment=False)
            b.command(f"G0 Z{format_number(z,3)}", comment)
            plan.add(MotionSegment("rapid", position.copy(), np.r_[position[:2], z], None, None, "rapid", comment))
            position[2] = z

        def rapid_xy_to(xy):
            nonlocal position, last_feed
            b.set_feature("rapid", comment=False)
            b.command(f"G0 X{format_number(xy[0],3)} Y{format_number(xy[1],3)} F{format_number(rapid_xy,1)}")
            plan.add(MotionSegment("rapid", position.copy(), np.r_[xy[:2], position[2]], None, None, "rapid"))
            position[:2] = xy[:2]
            last_feed = None

        def travel_at_depth(xy):
            nonlocal position, last_feed
            b.set_feature("rapid", comment=False)
            # G1 at rapid feed: a straight line is guaranteed (a G0 dog-leg is not).
            comment = "stay at depth: cleared by the previous pass"
            b.command(f"G1 X{format_number(xy[0],3)} Y{format_number(xy[1],3)} F{format_number(rapid_xy,1)}", comment)
            plan.add(MotionSegment("travel", position.copy(), np.r_[xy[:2], position[2]], None,
                                   float(rapid_xy), "rapid", comment))
            position[:2] = xy[:2]
            last_feed = None
            stay_count[0] += 1

        def feed_move(target, phase, state, cond=None, comment=None, measured=True, split=False, cleared_only=False):
            """Every feed move: measure engagement, apply the shared feed policy, write, update material.

            Returns False when ``cleared_only`` and the move would meet current material.
            """
            nonlocal position, last_feed, last_condition
            target = np.asarray(target, float)
            if split and state is not None:
                steps = list(split_move(position, target, active_radius, state.resolution))
            else:
                steps = [target]
            for q in steps:
                # Exact XY keeps planned stay-down endpoints matching; Z is the emitted value.
                q = np.array([q[0], q[1], float(format_number(q[2], 3))])
                if np.linalg.norm(q-position) < 1e-9:
                    continue
                if cleared_only and state is not None and state.contact(position, q, active_radius):
                    return False
                c = cond
                if measured and state is not None:
                    c = measure(state, position, q, active_radius, config, tool_values, machine_values)
                drop, run = position[2]-q[2], float(np.linalg.norm(q[:2]-position[:2]))
                steep = drop > 1e-9 and drop > RAMP_TAN*run
                rate = policy.rate(phase, feed, plunge, c, steep)
                segment = MotionSegment(phase, position.copy(), q.copy(), c, rate, policy.feature(phase, c), comment)
                key = (c.regime, c.hand) if c is not None else None
                text = comment if comment is not None else (segment.note if key is not None and key != last_condition else None)
                words = "G1"
                if run > 1e-9:
                    words += f" X{format_number(q[0],3)} Y{format_number(q[1],3)}"
                if abs(q[2]-position[2]) > 1e-9:
                    words += f" Z{format_number(q[2],3)}"
                b.set_feature(segment.feature)
                line = b.command(words+("" if rate == last_feed else f" F{feed_text(rate)}"), text)
                if c is not None:
                    line.engagement, line.note = c.engagement, segment.note
                if state is not None:
                    state.cut(position, q, active_radius)
                plan.add(segment)
                position = q
                last_feed = rate
                if key is not None:
                    last_condition = key
                samples[0] += 1
                if samples[0] > SURFACE_MAX_POINTS:
                    raise ValueError("CAM output exceeds the engagement sample budget; reduce the area or refine the setup")
            return True

        def descend(state, xy, z):
            """Final feed descent to an entry height: a plunge into material, or a verified-air approach."""
            if z < position[2]-1e-9:
                phase = "plunge" if entries.enters_material(state, xy, z, top=position[2]) else "approach"
                feed_move(np.r_[xy[:2], z], phase, state)

        def enter(state, xy, z, lead):
            """Shared travel to an entry: short retract, XY rapid, rapid descent, feed descent."""
            travel = links.travel_height(state, position, xy, z)
            if position[2] < travel-1e-9:
                rapid_z(travel)
            if state is not None and links.short_retracts and position[2] < safe_z-1e-9:
                short_count[0] += 1
            rapid_xy_to(xy)
            rapid_to = links.descent_height(state, position[2], xy, z, lead)
            if rapid_to < position[2]-1e-9:
                if state is not None and state.contact(position, np.r_[position[:2], rapid_to], active_radius):
                    raise ValueError(f"{name}: rapid descent to the entry is not clear of current material")
                rapid_z(rapid_to)
            descend(state, xy, z)

        def cut_material(start_index):
            return any(s.condition is not None and s.condition.engagement > 1e-6
                       for s in plan.segments[start_index:] if s.phase in ("cut", "link", "lead_in"))

        def surface_path(pts):
            """XYZ surface path: shared entry, lead-in only into material, measured cuts, cleared lead-out."""
            if surface_state[0] is None:
                from gcodeproducer.core.cam.stock import Stock
                estimate = Stock()
                estimate.auto(job.mesh)
                surface_state[0] = height_stock_for(job, estimate)
                ctx.log("  3D Contour: conservative model-bounds blank for entry/engagement; allocate stock for accurate material history")
            state = surface_state[0]
            length = (config.lead_length if config is not None else 0) or 2*active_radius
            lead, kind = (entries.surface(state, pts, length, name)
                          if config is not None and config.lead_in else (None, None))
            if kind == "zigzag":
                lead_kinds[kind] = lead_kinds.get(kind, 0)+1
            approach = lead[0] if lead is not None else pts[0]
            begin = len(plan.segments)
            enter(state, approach[:2], approach[2], lead is not None)
            if lead is not None:
                for q in lead[1:]:
                    feed_move(q, "lead_in", state, comment="surface path lead-in", split=True)
            cuts = len(plan.segments)
            for q in pts[1:]:
                feed_move(q, "cut", state, split=True)
            surface_totals.update(s.condition.regime for s in plan.segments[cuts:] if s.condition is not None)
            if config is not None and config.lead_out and cut_material(begin):
                exit_points = entries.surface_exit(pts, length)
                if exit_points is not None:
                    for q in exit_points[1:]:
                        if not feed_move(q, "lead_out", state, comment="cleared surface lead-out", split=True, cleared_only=True):
                            ctx.log(f"  {name}: surface lead-out crosses uncertain remaining cells; retracting instead")
                            break

        self._start(b, job, tool, rpm, safe_z, log=ctx.log, cutting=first_data)
        from gcodeproducer.core.gcode.simulation import simulate
        start_state=simulate(b.program())
        if len(start_state):position=np.array([start_state.x[-1],start_state.y[-1],start_state.z[-1]])
        b.set_feature("rapid", comment=False)

        n = max(1, len(job.layers))
        data=first_data
        rate_key=None
        previous_group = getattr(job.layers[0], "cam_group", None) if job.layers else None
        for li, layer in enumerate(job.layers):
            b.layer = li
            key=getattr(layer,"cam_operation_key",None)
            name=getattr(layer,"cam_operation",None)
            b.op = f"{key[0]+1}.{key[1]+1} {name}" if key is not None else name
            b.comment(f"LAYER:{li}")
            group = getattr(layer, "cam_group", None)
            next_tool = tool_map.get(getattr(layer, "cam_tool_id", None), tool)
            config=getattr(layer,"cam_operation_config",None)
            data=getattr(layer,"cam_cutting",None) or (resolve_cutting(job.machine,next_tool,stock,config) if next_tool else None)
            if group != previous_group:
                b.set_feature("rapid", comment=False)
                b.command(f"G0 Z{format_number(safe_z,3)}")
                b.command("M5", "spindle off before tool change")
                b.command(f"T{int(next_tool.get('tool_number', 1))} M6")
                b.command(f"M3 S{format_number(data.rpm if data else next_tool.get('spindle_rpm',18000),0)}")
                position[2]=safe_z
                rpm=data.rpm if data else rpm
                previous_group = group
            tool = next_tool
            active_radius=float(tool.get("diameter",0))/2 if tool else 0.
            tool_values = tool.resolved() if tool else {}
            entries = EntryExitPlanner(safe_z, lead_clearance, active_radius)
            links = LinkPlanner(safe_z, travel_clearance, lead_clearance, short_retracts, active_radius)
            if data and (li==0 or data.rpm!=rpm):
                b.command(f"M3 S{format_number(data.rpm,0)}","calculated / overridden RPM")
            rpm=data.rpm if data else rpm
            feed = data.feed if data else (tool.get("feed",800) if tool else feed)
            plunge = data.lead_feed if data else (tool.get("plunge_feed",300) if tool else plunge)
            current=(group,name,rpm,feed,plunge)
            if current!=rate_key:
                ctx.log(f"  {name or 'CAM'}: {data.material if data else 'legacy'} • {rpm:g} rpm • cut base {feed:g} • lead base {plunge:g} mm/min")
                rate_key=current
            if hasattr(layer, "cam_operation"):
                b.comment(f"Operation: {layer.cam_operation}")
            previous_end = None   # never carry stay-down permission across depth/operation/tool boundaries
            length = (config.lead_length if config is not None else 0) or 2*active_radius
            for path_index,path in enumerate(layer.paths):
                pts = np.asarray(path.points, float)
                if len(pts) < (1 if path.feature == "drill" else 2):
                    continue
                if pts.shape[1] == 3:
                    surface_path(pts)
                    previous_end = None
                    continue
                loop = np.vstack([pts, pts[0]]) if path.closed else pts
                start = loop[0]
                begin = len(plan.segments)
                if links.linked(path, previous_end):
                    last_feed = None   # links always state their feed
                    feed_move(np.r_[start, position[2]], "link", live, path.link_condition,
                              "stay-down link", measured=False)
                else:
                    want = config is not None and config.lead_in and len(pts) > 1
                    lead, kind = entries.planar(live, pts, path.closed, layer.z, length) if want else (None, None)
                    stayed = False
                    if config is not None and live is not None:
                        here = position[2]
                        down, down_kind = (entries.planar(live, pts, path.closed, layer.z, length, top=here)
                                           if want and layer.z+1e-9 < here < safe_z-1e-9 else (None, None))
                        target = down[0, :2] if down is not None else start
                        if links.stay_at_depth(live, position, target, layer.z):
                            lead, kind, stayed = down, down_kind, True
                            travel_at_depth(target)
                    if kind == "degenerate":
                        lead = None
                        warning=f"{name}: zero-length path; vertical entry used. Confirm the tool can plunge."
                        if warning not in job.warnings:job.warnings.append(warning)
                        ctx.log("LEAD WARNING: "+warning)
                    elif kind in ("helix","zigzag"):
                        lead_kinds[kind]=lead_kinds.get(kind,0)+1
                    approach = lead[0, :2] if lead is not None else start
                    entry = lead[0, 2] if lead is not None else layer.z
                    if stayed:
                        descend(live, approach, entry)
                    else:
                        enter(live, approach, entry, lead is not None)
                    if lead is not None:
                        for q in lead[1:]:
                            feed_move(q, "lead_in", live, comment="contour lead-in", split=True)
                    last_feed = None
                for i, q in enumerate(loop[1:]):
                    condition = path.cut_conditions[i] if i < len(path.cut_conditions) else None
                    feed_move(np.r_[q, position[2]], "cut", live, condition, measured=False)
                next_path=layer.paths[path_index+1] if path_index+1<len(layer.paths) else None
                if (config is not None and config.lead_out and len(pts)>1 and not (next_path and next_path.stay_down)
                        and (live is None or cut_material(begin) or not path.cut_conditions
                             or any(c.engagement > 1e-6 for c in path.cut_conditions))):
                    exit_points = entries.planar_exit(pts, path.closed, position[2], length)
                    if exit_points is not None:
                        for q in exit_points[1:]:
                            if not feed_move(q, "lead_out", live, comment="cleared contour lead-out", split=True, cleared_only=True):
                                ctx.log(f"  {name}: lead-out crosses uncertain remaining cells; retracting instead")
                                break
                previous_end = position[:2].copy()
            ctx.progress((li + 1) / n)

        self._end(b, job, safe_z, tool=tool, log=ctx.log, cutting=data)
        prog = b.program()
        prog.machine = "cam"
        prog.layer_z = [l.z for l in job.layers]
        job.program = prog
        if job.cam_setup is not None:
            from gcodeproducer.core.cam.stock import check_stock
            current_warnings,job.material_results = simulate_material(job,prog,ctx.log)
            stock_warnings = check_stock(job, prog, progressive=bool(job.material_results)) + current_warnings
            job.warnings = list(job.warnings) + stock_warnings
            for warning in stock_warnings:
                ctx.log(f"STOCK WARNING: {warning}")
            if pref(job,"highlight_conflicts"):
                flagged=mark_collisions(prog,stock_warnings)
                if flagged:ctx.log(f"  {flagged} flagged moves recoloured as Collision")
        if stay_count[0]:
            ctx.log(f"  {stay_count[0]} entries moved across cleared material at depth (no retract)")
        if short_count[0]:
            ctx.log(f"  {short_count[0]} entries used short retracts above current material instead of safe Z")
        for kind,count in sorted(lead_kinds.items()):
            what="circling the closed contour" if kind=="helix" else "back and forth along the open path"
            ctx.log(f"  {count} lead-in ramps longer than their path: {kind} ({what}) at <=10 degrees")
        if surface_totals:
            ctx.log("  3D engagement moves: " + ", ".join(f"{kind}={surface_totals[kind]}"
                    for kind in ("slot", "high", "cut", "hsm", "air")))
        for request, cap in sorted(policy.capped):
            ctx.log(f"  CAM feed capped: {request:g} -> {cap:g} mm/min (machine max_feed)")
        moves = sum(1 for ln in prog.lines if ln.cmd in ("G0", "G1"))
        return f"{len(prog.lines)} lines, {moves} moves, {len(job.layers)} depth passes"

    def _start(self, b, job, tool, rpm, safe_z, log=None, cutting=None):
        from gcodeproducer.core.gcode.variables import render_box
        b.comment(f"GCodeProducer CAM - {job.machine.name}")
        extra=_tool_variables(tool)
        if cutting:extra.update(tool=int(tool.get("tool_number",1)),spindle_rpm=cutting.rpm,feed=cutting.feed,plunge_feed=cutting.lead_feed,
                                machining_material=cutting.material,sfm=tool.get(f"{cutting.material}_sfm",0),
                                chip_load=tool.get(f"{cutting.material}_chip_load",0),axial_depth=cutting.stepdown)
        b.raw(render_box(job, "start_gcode", extra=extra, log=log).rstrip("\n"))

    def _end(self, b, job, safe_z, tool=None, log=None, cutting=None):
        from gcodeproducer.core.gcode.variables import render_box
        b.set_feature("retract", comment=False)
        last = job.layers[-1] if job.layers else None
        extra = _tool_variables(tool)
        if cutting:extra.update(spindle_rpm=cutting.rpm,feed=cutting.feed,plunge_feed=cutting.lead_feed,
                                machining_material=cutting.material,sfm=tool.get(f"{cutting.material}_sfm",0),
                                chip_load=tool.get(f"{cutting.material}_chip_load",0),axial_depth=cutting.stepdown)
        if last is not None:
            extra.update(layer=len(job.layers), layer_z=last.z)
        b.raw(render_box(job, "end_gcode", extra=extra, log=log).rstrip("\n"))


def _tool_variables(tool):
    if tool is None:
        return {}
    return {"tool": int(tool.get("tool_number", 1)), "tool_name": tool.name,
            "tool_diameter": tool.get("diameter", 0), "spindle_rpm": tool.get("spindle_rpm", 18000),
            "feed": tool.get("feed", 800), "plunge_feed": tool.get("plunge_feed", 300)}
