"""Sequencer — the planner's job loop over tool groups and operations.

For every enabled operation, in execution order, the sequencer resolves its
tool, cutting data, depths and selection, then calls the operation-kind
generator with a :class:`PlanningContext`. Material history flows through the
one :class:`MaterialModel` across operations and tool changes.
"""
from __future__ import annotations
import math


class Sequencer:
    def run(self, job, ctx):
        from gcodeproducer.core.cam.planning import cached_topology
        from gcodeproducer.core.cam.tabs import resolve_tabs
        from gcodeproducer.core.settings.preferences import pref
        from .material_model import MaterialModel
        from .planning_context import PlanningContext
        setup = job.cam_setup
        tabs = resolve_tabs(job.mesh, setup)
        if tabs:
            ctx.log(f"  {len(tabs)} holding tabs protected across all operations")
        planning = PlanningContext(job, ctx, cached_topology(job.mesh, setup.reference_shapes),
                                   MaterialModel(job), tabs, bool(pref(job, "skip_air_cuts")))
        job.warnings = []
        tools = {t.id: t for t in job.tools}
        if job.m("auto_tool_change", True):   # manual changes are per file, not by T number
            self.check_tool_numbers(setup, tools, planning, int(job.m("max_tool_number", 0) or 0))
        for gi, group in enumerate(setup.groups):
            if group.tool_id not in tools:
                raise ValueError(f"CAM tool '{group.tool_id}' is missing or not allowed by the machine")
            tool = tools[group.tool_id]
            if float(tool.get("diameter", 0)) <= 0:
                raise ValueError("Tool diameter must be positive")
            for oi, op in enumerate(group.operations):
                if op.enabled:
                    self.operation(job, planning, tool, gi, oi, op)
                    if planning.debug_partial:
                        ctx.log('DEBUG ONLY: remaining CAM depths and operations omitted after incomplete clearing.')
                        break
            if planning.debug_partial:
                break
            ctx.progress((gi + 1) / max(1, len(setup.groups)))
        if not planning.layers:
            raise ValueError("CAM setup has no enabled operations that remove material")
        job.layers = planning.layers
        return f"{len(setup.groups)} tool groups, {len(planning.layers)} depth passes"

    @staticmethod
    def check_tool_numbers(setup, tools, planning, highest=0):
        numbers = {}
        for group in setup.groups:
            tool = tools.get(group.tool_id)
            if tool is not None:
                number = int(tool.get("tool_number", 1))
                if highest and not 1 <= number <= highest:
                    planning.warn(f"Tool number T{number} ({tool.name}) is outside the tool changer's range "
                                  f"T1-T{highest}; the machine cannot load it.", "TOOL")
                if number in numbers and numbers[number] != tool.id:
                    planning.warn(f"Tool number T{number} is shared by different tool profiles; "
                                  "verify the physical tool change.", "TOOL")
                numbers[number] = tool.id

    def operation(self, job, planning, tool, gi, oi, op):
        from gcodeproducer.core.cam.cam_constants import KINDS, SURFACE_KINDS
        from gcodeproducer.core.cam.depth import Depth
        from gcodeproducer.core.cam.cutting import resolve_cutting
        from gcodeproducer.core.cam.paths import direction_for
        from gcodeproducer.core.cam.operations import generator_for
        from .operation_run import OperationRun
        from .selection import Selection
        setup, topo, ctx = planning.setup, planning.topo, planning.ctx
        if op.kind not in KINDS or not op.geometry:
            raise ValueError(f"{op.name}: select machining geometry first")
        start = op.start.resolve(job.mesh, topo, op.geometry, setup.stock)
        end = op.end.resolve(job.mesh, topo, op.geometry, setup.stock)
        if ((op.kind == "pocket" or op.kind in SURFACE_KINDS) and op.start.source == "selection"
                and math.isfinite(start) and math.isfinite(end) and start <= end + 1e-6):
            # A single flat floor selection has no higher edge: begin at the material
            # surface (air-cut removal then drops to the current material top).
            start = Depth("stock_top", op.start.value).resolve(job.mesh, topo, op.geometry, setup.stock)
            ctx.log(f"  {op.name}: flat selection; start taken from the material surface Z{start:g}")
        if not (math.isfinite(start) and math.isfinite(end)) or end > start:
            raise ValueError(f"{op.name}: end Z must be at or below start Z")
        if not op.auto_stepdown and (op.stepdown <= 0 or not math.isfinite(op.stepdown)):
            raise ValueError(f"{op.name}: stepdown must be positive")
        cutting = resolve_cutting(job.machine, tool, setup.stock, op)
        step = cutting.stepdown
        if step <= 0 or not math.isfinite(step):
            raise ValueError(f"{op.name}: tool depth per pass must be positive")
        count = max(1, math.ceil((start - end) / step))
        if count > 10000:
            raise ValueError(f"{op.name}: too many depth passes")
        safe = float(job.m("safe_z", 15))
        if safe <= max(float(job.mesh.bounds[1][2]), start, setup.stock.top if setup.stock.allocated else -math.inf):
            raise ValueError("Safe Z must be above the model and all operation start heights")
        generator = generator_for(op.kind)
        selection = Selection.resolve(op, topo, setup, generator.clearing)
        if op.area_order not in ("area", "depth"):
            raise ValueError(f"{op.name}: unknown area order '{op.area_order}'")
        from gcodeproducer.core.cam.tool_reach import reach_problems
        top = setup.stock.top if setup.stock.allocated else float(job.mesh.bounds[1][2])
        _, too_deep = reach_problems(tool, op.name, 0., max(top, start)-end)
        if too_deep:
            raise ValueError(too_deep)
        run = OperationRun(op, tool, gi, oi, cutting, start, end, step, count, direction_for(job, op))
        generator.validate(run, selection)
        generator.generate(run, selection, planning)
