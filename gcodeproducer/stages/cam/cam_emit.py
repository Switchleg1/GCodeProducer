"""CAM stage: emit G-code from the milling toolpaths.

Rapids at safe Z, plunges at the tool plunge feed, cuts at the tool feed, with
spindle control.  Feeds and speeds come from the tool; clearances and rapids
from the machine profile.
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
        from gcodeproducer.core.cam.leads import ramp_entry
        from gcodeproducer.core.cam.leads import exit_path
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
        max_feed = float(job.m("max_feed", 0) or 0)
        if not math.isfinite(max_feed) or max_feed < 0:
            raise ValueError("Machine max feed must be nonnegative and finite")
        capped = set()
        lead_kinds = {}
        short_retracts = bool(pref(job,"short_retracts"))
        lead_clearance = max(.05, float(pref(job,"lead_clearance")))
        travel_clearance = max(.1, float(pref(job,"retract_clearance")))
        short_count = [0]
        stay_count = [0]
        last_feed = None
        last_condition = None

        def limited(value):
            if not math.isfinite(value) or value <= 0:
                raise ValueError("CAM cutting/plunge feeds must be positive and finite")
            if max_feed > 0 and value > max_feed:
                capped.add((value, max_feed))
                value=max_feed
            if value<.0001:
                raise ValueError("Effective CAM feed is too small to represent safely (below 0.0001 mm/min)")
            return value

        def feed_text(value):
            return format_number(value,4 if value<1 else 1)

        def cut_move(point, condition=None, comment=None, force=False):
            nonlocal last_feed, last_condition, position
            factor = condition.feed_factor if condition is not None else 1.0
            requested = limited(float(feed)*factor)
            feature = ({"slot": "slot", "high": "high_engagement", "hsm": "hsm", "air": "air"}.get(condition.regime, "cut")
                       if condition is not None else "cut")
            if condition is not None and condition.conflict and pref(job,"highlight_conflicts"):
                feature = "conflict"
            b.set_feature(feature)
            note = None
            if condition is not None:
                note = f"{condition.regime} {condition.engagement*100:.2f}% engagement; {condition.hand}"
                key = (condition.regime, condition.hand)
                if key != last_condition and comment is None:
                    comment = note
                last_condition = key
            f = f" F{feed_text(requested)}" if force or last_feed != requested else ""
            line = b.command(f"G1 X{format_number(point[0],3)} Y{format_number(point[1],3)}{f}", comment)
            if condition is not None:
                line.engagement = condition.engagement
                line.note = note
            if live is not None:
                target=np.r_[point[:2],position[2]]
                live.cut(position,target,active_radius)
            position[:2]=point[:2]
            last_feed = requested

        def move3(command,target,rate,feature,comment=None):
            nonlocal position,last_feed
            target=np.asarray(target,float).copy()
            target[2]=float(format_number(target[2],3))
            b.set_feature(feature)
            f=f" F{feed_text(limited(float(rate)))}" if rate is not None and command=="G1" else ""
            line=b.command(f"{command} X{format_number(target[0],3)} Y{format_number(target[1],3)} Z{format_number(target[2],3)}{f}",comment)
            if live is not None and command=="G1":
                contact=live.contact(position,target,active_radius)
                line.engagement=1. if contact else 0.
                live.cut(position,target,active_radius)
            position=target.copy()
            last_feed=None

        def surface_path(pts):
            """One (n, 3) surface-following path: clear travel, plunge, then XYZ feed moves.

            Descents steeper than the lead-in ramp angle use the lead/plunge feed.
            """
            nonlocal position, last_feed
            first = pts[0]
            b.set_feature("rapid", comment=False)
            travel = safe_z
            if live is not None and short_retracts:
                travel = min(safe_z, max(live.max_height_along(position[:2], first[:2], active_radius),
                                         live.height_at(first[:2], active_radius))+travel_clearance)
            travel = max(travel, float(first[2]))
            if position[2] < travel-1e-9:
                b.command(f"G0 Z{format_number(travel,3)}")
                position[2] = travel
            b.command(f"G0 X{format_number(first[0],3)} Y{format_number(first[1],3)} F{format_number(rapid_xy,1)}")
            position[:2] = first[:2]
            if live is not None and short_retracts:
                local = live.height_at(first[:2], active_radius)+travel_clearance
                rapid_to = max(float(first[2]), min(position[2], local))
                if rapid_to < position[2]-1e-9:
                    b.command(f"G0 Z{format_number(rapid_to,3)}")
                    position[2] = rapid_to
            current = None
            for index, q in enumerate(pts):
                target = np.array([q[0], q[1], float(format_number(q[2],3))])
                if index == 0 and target[2] >= position[2]-1e-9:
                    continue
                drop, run = position[2]-target[2], float(np.linalg.norm(target[:2]-position[:2]))
                steep = drop > 1e-9 and drop > RAMP_TAN*run
                rate = limited(float(plunge if steep else feed))
                b.set_feature("plunge" if steep else "cut", comment=False)
                words = f"G1 X{format_number(target[0],3)} Y{format_number(target[1],3)} Z{format_number(target[2],3)}"
                line = b.command(words+("" if rate == current else f" F{feed_text(rate)}"))
                current = rate
                if live is not None:
                    line.engagement = 1. if live.contact(position, target, active_radius) else 0.
                    live.cut(position, target, active_radius)
                position = target.copy()
            last_feed = None

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
                linked = (path.stay_down and previous_end is not None and path.stay_down_from is not None
                          and np.allclose(previous_end, path.stay_down_from, atol=1e-7, rtol=0))
                if linked:
                    cut_move(start, path.link_condition, "stay-down link", force=True)
                else:
                    lead=None
                    clearance=max(.1,float(job.m("clearance_z",1)))
                    if config is not None and config.lead_in and len(pts)>1 and live is not None:
                        surface=live.height_at(start,active_radius)
                        for _ in range(3):
                            # The rapid descent happens above the ramp *start*, which moves with the
                            # ramp length; settle the entry plane over both points (usually one pass).
                            # The ramp begins just above the material (lead clearance), not at the
                            # rapid clearance plane, so it does not spend its length cutting air.
                            entry_z=min(safe_z,max(surface,layer.z)+lead_clearance)
                            lead,kind=ramp_entry(pts,path.closed,layer.z,entry_z,config.lead_length or 2*active_radius)
                            if lead is None:break
                            above=live.height_at(lead[0,:2],active_radius)
                            if above<=surface+1e-6:break
                            surface=above
                        if lead is None:
                            warning=f"{name}: zero-length path; vertical entry used. Confirm the tool can plunge."
                            if warning not in job.warnings:job.warnings.append(warning)
                            ctx.log("LEAD WARNING: "+warning)
                        elif kind in ("helix","zigzag"):
                            lead_kinds[kind]=lead_kinds.get(kind,0)+1
                    approach=lead[0,:2] if lead is not None else start
                    entry=lead[0,2] if lead is not None else layer.z
                    stayed=False
                    if (live is not None and short_retracts and position[2]<safe_z-1e-9
                            and position[2]>layer.z+1e-9 and config is not None):
                        # Already down in material this operation has cleared (typically the floor of
                        # the previous pass): move across at the current Z and ramp down from here,
                        # instead of going up at all. Allowed only if the straight move and the ramp
                        # start are free of CURRENT material under the full cutter radius.
                        here=position[2]
                        down_lead=None
                        if lead is not None:
                            down_lead,_=ramp_entry(pts,path.closed,layer.z,here,config.lead_length or 2*active_radius)
                        target=down_lead[0,:2] if down_lead is not None else start
                        moved=np.r_[target,here]
                        if (live.height_at(target,active_radius)<=here+1e-6
                                and not live.contact(position,moved,active_radius)):
                            if lead is not None:lead=down_lead
                            approach,entry,stayed=target,(down_lead[0,2] if down_lead is not None else layer.z),True
                            b.set_feature("rapid", comment=False)
                            # G1 at rapid feed: a straight line is guaranteed (a G0 dog-leg is not).
                            b.command(f"G1 X{format_number(approach[0],3)} Y{format_number(approach[1],3)} F{format_number(rapid_xy,1)}",
                                      "stay at depth: cleared by the previous pass")
                            position[:2]=approach
                            stay_count[0]+=1
                    b.set_feature("rapid", comment=False)
                    if stayed:
                        pass
                    elif live is not None and short_retracts:
                        # Retract only as high as the CURRENT material along the XY travel needs
                        # (plus clearance), not to safe Z: inside a cleared pocket the tool stays low.
                        # Cutter radius, the same footprint the rapid-contact check uses; walls stand
                        # outside it because contours keep the cutter radius from the retained part.
                        margin=active_radius
                        travel=min(safe_z,max(live.max_height_along(position[:2],approach,margin),
                                              live.height_at(approach,margin))+travel_clearance)
                        travel=max(travel,entry)
                        if position[2]<travel-1e-9:
                            b.command(f"G0 Z{format_number(travel,3)}")
                            position[2]=travel
                        else:
                            travel=position[2]
                        short_count[0]+=travel<safe_z-1e-9
                    else:
                        b.command(f"G0 Z{format_number(safe_z,3)}")
                        position[2]=safe_z
                    if not stayed:
                        b.command(f"G0 X{format_number(approach[0],3)} Y{format_number(approach[1],3)} F{format_number(rapid_xy,1)}")
                        position[:2]=approach
                    if live is not None and short_retracts and not stayed:
                        # Rapid down to the clearance plane above the local material, then feed.
                        # Rapid straight to the ramp start (which already sits lead_clearance above the
                        # local material), or to clearance above the material for a plain plunge.
                        local=live.height_at(approach,active_radius)+(lead_clearance if lead is not None else travel_clearance)
                        rapid_to=max(entry,min(position[2],local))
                        if rapid_to<position[2]-1e-9:
                            b.command(f"G0 Z{format_number(rapid_to,3)}")
                            position[2]=rapid_to
                    if entry<position[2]-1e-9:
                        b.set_feature("plunge", comment=False)
                        b.command(f"G1 Z{format_number(entry,3)} F{feed_text(limited(float(plunge)))}")
                        if live is not None:live.cut(position,np.r_[approach,entry],active_radius)
                        position[2]=float(format_number(entry,3))
                    if lead is not None:
                        for q in lead[1:]:
                            rate=plunge*(float(job.m("slotting_feed",50))/100 if live.contact(position,q,active_radius) else 1)
                            move3("G1",q,rate,"lead_in","contour lead-in")
                    last_feed = None
                for i, q in enumerate(loop[1:]):
                    condition = path.cut_conditions[i] if i < len(path.cut_conditions) else None
                    cut_move(q, condition, force=i == 0)
                next_path=layer.paths[path_index+1] if path_index+1<len(layer.paths) else None
                if config is not None and config.lead_out and len(pts)>1 and not (next_path and next_path.stay_down):
                    exit_xy=exit_path(pts,path.closed,config.lead_length or 2*active_radius)
                    if exit_xy is not None:
                        for q in exit_xy[1:]:
                            target=np.r_[q,layer.z]
                            if live is not None and live.contact(position,target,active_radius):
                                ctx.log(f"  {name}: lead-out crosses uncertain remaining cells; retracting instead")
                                break
                            move3("G1",target,plunge,"lead_out","cleared contour lead-out")
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
        for request, cap in sorted(capped):
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
