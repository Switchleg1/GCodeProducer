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
import numpy as np
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
        """Plan the motion with the CAM motion planner, then serialize it to G-code."""
        from gcodeproducer.core.cam.cutting import resolve_cutting
        from gcodeproducer.core.cam.material import simulate_material
        from gcodeproducer.core.settings.preferences import pref
        from gcodeproducer.core.cam.planner.motion_planner import MotionPlanner
        b = GCodeBuilder(relative_e=False)
        b.e = 0.0
        tool_map = {t.id: t for t in job.tools}
        first_id = getattr(job.layers[0], "cam_tool_id", None) if job.layers else None
        tool = tool_map.get(first_id) or (job.tools[0] if job.tools else None)
        stock = getattr(job.cam_setup,"stock",None)
        if stock is None and job.settings.get("machining_material"):
            from gcodeproducer.core.cam.stock import Stock
            stock=Stock(category=job.settings["machining_material"])
        if stock is None and any(t.get("auto_cutting_data",False) for t in job.tools):
            raise ValueError("Automatic CAM tools need a machining material category (CLI: --cam-material)")
        first_op = getattr(job.layers[0],"cam_operation_config",None) if job.layers else None
        first_data = resolve_cutting(job.machine,tool,stock,first_op) if tool else None
        safe_z = job.m("safe_z", 15.0)
        rpm = first_data.rpm if first_data else (tool.get("spindle_rpm",18000) if tool else job.m("spindle_max",18000))
        self._start(b, job, tool, rpm, safe_z, log=ctx.log, cutting=first_data)
        from gcodeproducer.core.gcode.simulation import simulate
        start_state = simulate(b.program())
        position = (np.array([start_state.x[-1], start_state.y[-1], start_state.z[-1]])
                    if len(start_state) else np.zeros(3))
        b.set_feature("rapid", comment=False)
        modal = None, None

        def write_chunk(segments):
            nonlocal modal
            modal = self._serialize_segments(b, segments, modal)

        planner = MotionPlanner(job, ctx, stock, position, rpm, consume=write_chunk)
        job.motion_plan = planner.run(tool, first_data)
        tool, data = planner.tool or tool, planner.data
        self._end(b, job, safe_z, tool=tool, log=ctx.log, cutting=data)
        prog = b.program()
        prog.machine = "cam"
        prog.layer_z = [l.z for l in job.layers]
        job.program = prog
        if job.cam_setup is not None:
            from gcodeproducer.core.cam.stock import check_stock
            allocated = job.cam_setup.stock is not None and job.cam_setup.stock.allocated
            sim = simulate(prog) if allocated else None
            current_warnings,job.material_results = simulate_material(job,prog,ctx.log,sim=sim)
            stock_warnings = check_stock(job, prog, sim=sim, progressive=bool(job.material_results)) + current_warnings
            job.warnings = list(job.warnings) + stock_warnings
            for warning in stock_warnings:
                ctx.log(f"STOCK WARNING: {warning}")
            if pref(job,"highlight_conflicts"):
                flagged=mark_collisions(prog,stock_warnings)
                if flagged:ctx.log(f"  {flagged} flagged moves recoloured as Collision")
        moves = sum(1 for ln in prog.lines if ln.cmd in ("G0", "G1"))
        return f"{len(prog.lines)} lines, {moves} moves, {len(job.layers)} depth passes"

    @staticmethod
    def serialize(b, plan):
        """Write a MotionPlan as G-code: axis words, modal feed, comments and line metadata only."""
        if not plan.complete:
            raise ValueError('Streamed motion plan contains only an inspection prefix')
        CAMEmit._serialize_segments(b, plan.segments, (None, None))

    @staticmethod
    def _serialize_segments(b, segments, modal):
        def feed_text(value):
            return format_number(value, 4 if value < 1 else 1)
        last_feed, last_key = modal
        for s in segments:
            b.layer, b.op = s.layer, s.op
            if s.phase == "comment":
                b.comment(s.words)
                continue
            if s.phase == "command":
                b.set_feature("rapid", comment=False)
                b.command(s.words, s.comment)
                continue
            start, end = s.start, s.end
            xy = float(np.linalg.norm(end[:2]-start[:2])) > 1e-9
            if s.phase == "rapid":
                b.set_feature("rapid", comment=False)
                if xy:
                    b.command(f"G0 X{format_number(end[0],3)} Y{format_number(end[1],3)} F{format_number(s.rate,1)}",
                              s.comment)
                    last_feed = None
                else:
                    b.command(f"G0 Z{format_number(end[2],3)}", s.comment)
                continue
            if s.phase == "travel":
                b.set_feature("rapid", comment=False)
                b.command(f"G1 X{format_number(end[0],3)} Y{format_number(end[1],3)} F{format_number(s.rate,1)}",
                          s.comment)
                last_feed = None
                continue
            words = "G1"
            if xy:
                words += f" X{format_number(end[0],3)} Y{format_number(end[1],3)}"
            if abs(end[2]-start[2]) > 1e-9:
                words += f" Z{format_number(end[2],3)}"
            c = s.condition
            key = (c.regime, c.hand) if c is not None else None
            note = s.note
            text = s.comment if s.comment is not None else (note if key is not None and key != last_key else None)
            b.set_feature(s.feature)
            stated = s.force_feed or s.rate != last_feed
            line = b.command(words+(f" F{feed_text(s.rate)}" if stated else ""), text)
            if c is not None:
                line.engagement, line.note = c.engagement, note
            last_feed = s.rate
            if key is not None:
                last_key = key
        return last_feed, last_key

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
