"""MotionPlanner — turns the sequenced passes (job.layers) into a complete MotionPlan.

The planner owns the program loop: tool changes and spindle speeds, links
between paths, entries (lead-in only into material, verified-air approach,
plunge), leads, cutting moves and exits, engagement measurement on the height
sampler, feed policy and the material update. The G-code writer serializes the
resulting segments and makes no decisions.
"""
from __future__ import annotations
import math
import numpy as np
from gcodeproducer.core.cam.cam_constants import RAMP_ANGLE, RAMP_TAN, PLUNGE_FEED_FIELD
from gcodeproducer.core.gcode.parsing import format_number
from .motion_segment import MotionSegment
from .motion_plan import MotionPlan
from .feed_policy import FeedPolicy
from .entry_exit_planner import EntryExitPlanner
from .link_planner import LinkPlanner


def _same_band(a, b):
    if a is None or b is None:
        return a is b
    return (a.regime, a.hand, a.feed_factor, a.conflict) == (b.regime, b.hand, b.feed_factor, b.conflict)


def _wider(a, b):
    """Merged sub-moves report their peak engagement."""
    return a if a is None or a.engagement >= b.engagement else b


def _nearest_order(runs, position):
    """Greedy nearest-start order (ties keep the planned order); pieces are not reversed."""
    if len(runs) < 3:
        return list(range(len(runs)))
    starts = np.array([run[0, :2] for run in runs])
    ends = np.array([run[-1, :2] for run in runs])
    left = np.ones(len(runs), bool)
    order, here = [], np.asarray(position, float)[:2]
    for _ in range(len(runs)):
        distance = np.where(left, np.hypot(*(starts-here).T), np.inf)
        k = int(distance.argmin())
        order.append(k)
        left[k] = False
        here = ends[k]
    return order


class MotionPlanner:
    def __init__(self, job, ctx, stock, position, rpm, *, consume=None):
        from collections import Counter
        from gcodeproducer.core.settings.preferences import pref
        from .material_model import MaterialModel
        self.job, self.ctx, self.stock = job, ctx, stock
        self.position = np.asarray(position, float).copy()
        self.rpm = rpm
        self.material = MaterialModel(job, stock, log=ctx.log)
        self.policy = FeedPolicy(job.m("max_feed", 0), pref(job, "highlight_conflicts"))
        from .feed_smoother import FeedSmoother
        self.smoother = FeedSmoother(pref(job, "cam_feed_smoothing"), bool(pref(job, "cam_merge_moves")))
        self.plan = MotionPlan(consume, smoother=self.smoother)
        self.safe_z = job.m("safe_z", 15.0)
        self.rapid_feed = job.m("rapid_xy", 3000)
        self.short_retracts = bool(pref(job, "short_retracts"))
        self.lead_clearance = max(.05, float(pref(job, "lead_clearance")))
        self.travel_clearance = max(.1, float(pref(job, "retract_clearance")))
        self.sample_spacing = max(0., float(pref(job, "cam_engagement_step")))
        self.merge_moves = bool(pref(job, "cam_merge_moves"))
        self.skip_air = bool(pref(job, "skip_air_cuts"))
        self.auto_tool_change = bool(job.m("auto_tool_change", True))
        self.files = 1
        self.air_skipped = 0.
        self.air_paths = 0
        self.machine = job.machine.resolved()
        from gcodeproducer.core.cam.engagement import engagement_band
        engagement_band(.5, self.machine)   # validate thresholds even for an all-air program
        self.lead_kinds = {}
        self.stay_count = self.short_count = self.samples = 0
        self.surface_totals = Counter()
        self.air_bound = None
        self._path_cut_material = False
        self._layer_entered = False
        self.lead_outs_skipped = 0
        self._surface_cut = False
        self.layer, self.op = 0, None
        self.tool = self.config = self.name = self.model = None
        self.feed = self.plunge = self.lead = 0.0
        self.radius = 0.0
        self.entries = self.links = None

    # ------------------------------------------------------------- segments
    def add(self, phase, end=None, condition=None, rate=None, feature="rapid", comment=None,
            words=None, force_feed=False, start=None, payload=None):
        if end is not None and start is None:
            start = self.position.copy()
        segment = MotionSegment(phase, start, None if end is None else np.asarray(end, float).copy(),
                                condition, rate, feature, comment, self.layer, self.op, words, force_feed, payload)
        self.plan.add(segment)
        if condition is not None:
            if phase in ('cut', 'link', 'lead_in') and condition.engagement > 1e-6:
                self._path_cut_material = True
            if self._surface_cut and phase == 'cut':
                self.surface_totals[condition.regime] += 1
        if end is not None:
            self.position = segment.end.copy()
        return segment

    def comment(self, text):
        self.add("comment", words=text)

    def command(self, words, comment=None):
        self.add("command", words=words, comment=comment)

    def rapid_z(self, z, comment=None):
        self.add("rapid", np.r_[self.position[:2], float(format_number(z, 3))], comment=comment)

    def rapid_xy(self, xy):
        self.add("rapid", np.r_[np.asarray(xy, float)[:2], self.position[2]], rate=float(self.rapid_feed))

    def travel_at_depth(self, xy):
        # G1 at rapid feed: a straight line is guaranteed (a G0 dog-leg is not).
        xy = np.asarray(xy, float)[:2]
        if np.linalg.norm(xy - self.position[:2]) < 1e-9:
            return
        self.add("travel", np.r_[xy, self.position[2]], rate=float(self.rapid_feed),
                 comment="stay at depth: cleared by the previous pass")

    def sampler(self, state):
        from .height_sampler import HeightSampler
        return HeightSampler(state) if state is not None else None

    def feed_move(self, target, phase, state, cond=None, comment=None, measured=True, split=False,
                  cleared_only=False, force_feed=False):
        """Every feed move: measure engagement, apply the shared feed policy, update material.

        Returns False when ``cleared_only`` and the move would meet current material.
        """
        from gcodeproducer.core.cam.surface_engagement import split_move
        from .planner_constants import MERGE_PHASES
        target = np.asarray(target, float)
        sampler = self.sampler(state)
        # Every flat-endmill operation: a move the height grid reads as air is checked against a second
        # grid that only credits cells a cutter covered whole, and is fed as a cut where that one
        # still shows stock (a skin thinner than a cell beside a wall, the edge of a ring).
        bounded = (state is not None and self.config is not None and self.tool is not None
                   and self.tool.get('type', 'endmill') == 'endmill')
        if bounded:
            if self.air_bound is None or self.air_bound[0] is not state:
                from copy import copy
                upper = copy(state)
                upper.heights = np.full_like(state.heights, state.stock.top)
                upper._last_sweep = None
                self.air_bound = state, upper
            upper = self.air_bound[1]
            # Half the cell diagonal encloses every point in the cell; allow
            # for XY rounding too. Credit only cells fully under the disk.
            margin = .5*math.hypot(state.dx, state.dy) + .002
        track = (state is not None and self.tool is not None and not state.tabs
                 and self.tool.get('type', 'endmill') == 'endmill')
        if track and not hasattr(state, 'hybrid'):
            from ..hybrid_stock import HybridStock
            state.hybrid = HybridStock.for_height_state(state)
        adaptive = getattr(self.config, 'strategy', None) == 'adaptive'
        split = split and state is not None
        steps = (split_move(self.position, target, self.radius, state.resolution, self.sample_spacing)
                 if split else (target,))
        # Sub-moves of one straight move are collinear (up to emitted Z rounding).
        merge = split and self.merge_moves and phase in MERGE_PHASES
        pending = None                                  # [start, end, condition, rate, feature, force]

        def flush():
            nonlocal pending
            if pending is not None:
                first, last, condition, rate, feature, force = pending
                self.add(phase, last, condition, rate, feature, comment, force_feed=force, start=first)
                pending = None

        for q in steps:
            # Exact XY keeps planned stay-down endpoints matching; Z is the emitted value.
            q = np.array([q[0], q[1], float(format_number(q[2], 3))])
            if np.linalg.norm(q-self.position) < 1e-9:
                continue
            if cleared_only and state is not None and state.contact(self.position, q, self.radius):
                flush()
                return False
            c = cond
            if measured and sampler is not None:
                c = self.model.condition(sampler, self.position, q, self.radius)
            if bounded and c is not None and c.regime == 'air' and (adaptive or phase in ('cut', 'link')):
                doubtful = upper.contact(self.position, q, self.radius + margin)
                if doubtful and not adaptive:
                    # The whole-cell grid also reads a cutter retracing its own pass as touching the
                    # walls of that pass. Outside Adaptive, settle a level move by the recorded
                    # sweeps themselves; a move that changes height keeps the grid's reading (air).
                    detail = getattr(state, 'hybrid', None)
                    z = float(q[2])
                    level = abs(float(self.position[2])-z) < 1e-9
                    doubtful = (level and detail is not None and detail.bottom <= z < detail.top
                                and not detail.clear_at_depth(self.position[:2], q[:2], self.links.probe, z))
                if doubtful:
                    if cleared_only:
                        flush()
                        return False
                    c = self.model.condition(self.sampler(upper), self.position, q, self.radius + margin)
            drop, run = self.position[2]-q[2], float(np.linalg.norm(q[:2]-self.position[:2]))
            # Down into material steeper than the operation's lead-in ramp is a plunge;
            # the feed follows the descent angle (see FeedPolicy.rate).
            max_slope = self.entries.ramp_slope if self.entries is not None else RAMP_TAN
            # (Emitted Z is rounded to 0.001 mm: a ramp at exactly the lead angle must not read as steeper.)
            steep = drop > 1e-9 and drop > max_slope*run*1.02+.002
            angle = 0. if drop <= 1e-9 else (90. if steep and run < 1e-9 else
                                             math.degrees(math.atan2(drop, run)))
            if drop > 1e-9 and not steep:   # within rounding of the lead-in angle: at most that angle
                angle = min(angle, math.degrees(math.atan(max_slope)))
            rate = self.policy.rate(phase, self.feed, self.lead, c, steep, self.plunge, angle,
                                    math.degrees(math.atan(max_slope)))
            feature = self.policy.feature(phase, c, steep)
            start = self.position.copy()
            if pending is not None and pending[3] == rate and pending[4] == feature and _same_band(pending[2], c):
                pending[1], pending[2] = q, _wider(pending[2], c)
                self.position = q
            else:
                flush()
                if merge:
                    pending = [start, q, c, rate, feature, force_feed]
                    self.position = q
                else:
                    self.add(phase, q, c, rate, feature, comment, force_feed=force_feed)
            force_feed = False
            if sampler is not None:
                sampler.remove_move(start, q, self.radius)
            if bounded and self.radius > margin:
                upper.cut(start, q, self.radius - margin)
            if track and min(start[2], q[2]) < state.stock.top and self.radius > .002:
                # Under-credit to account for XY post rounding. Unrecorded paths
                # leave excess stock in this veto-only clearance model.
                state.hybrid.cut(start, q, self.radius - .002)
            self.samples += 1
        flush()
        return True

    def descend(self, state, xy, z):
        """Final feed descent to an entry height: a plunge into material, or a verified-air approach."""
        if z < self.position[2]-1e-9:
            phase = "plunge" if self.entries.enters_material(state, xy, z, top=self.position[2]) else "approach"
            self.feed_move(np.r_[np.asarray(xy, float)[:2], z], phase, state)

    def enter(self, state, xy, z, lead):
        """Shared travel to an entry: short retract, XY rapid, rapid descent, feed descent."""
        travel = self.links.travel_height(state, self.position, xy, z)
        if self.position[2] < travel-1e-9:
            self.rapid_z(travel)
        if state is not None and self.links.short_retracts and self.position[2] < self.safe_z-1e-9:
            self.short_count += 1
        self.rapid_xy(xy)
        rapid_to = self.links.descent_height(state, self.position[2], xy, z, lead)
        if rapid_to < self.position[2]-1e-9:
            if state is not None and state.contact(self.position, np.r_[self.position[:2], rapid_to], self.links.reach):
                raise ValueError(f"{self.name}: rapid descent to the entry is not clear of current material")
            self.rapid_z(rapid_to)
        self.descend(state, xy, z)

    # ---------------------------------------------------------------- paths
    def _material_runs(self, state, pts):
        """Pieces of an XYZ path that touch current material, joined across short air gaps.

        Material only ever decreases, so a sub-move clear of material now stays
        clear while this path cuts: skipping it cannot leave material behind.
        """
        from gcodeproducer.core.cam.surface_engagement import split_move
        from .planner_constants import AIR_GAP_DIAMETERS
        subs = []                     # (start, end, ends an original vertex, touches material)
        for i in range(len(pts)-1):
            a = pts[i]
            steps = list(split_move(a, pts[i+1], self.radius, state.resolution, self.sample_spacing))
            for k, q in enumerate(steps):
                subs.append((a, q, k == len(steps)-1, state.contact(a, q, self.radius)))
                a = q
        hits = [k for k, s in enumerate(subs) if s[3]]
        if not hits:
            return []
        gap = AIR_GAP_DIAMETERS*2*self.radius
        ranges, first, last = [], hits[0], hits[0]
        for k in hits[1:]:
            air = sum(float(np.linalg.norm(subs[j][1][:2]-subs[j][0][:2])) for j in range(last+1, k))
            if air > gap:
                ranges.append((first, last))
                first = k
            last = k
        ranges.append((first, last))
        if ranges == [(0, len(subs)-1)]:
            return [pts]
        runs = []
        for s, e in ranges:
            points = [subs[s][0]] + [subs[k][1] for k in range(s, e) if subs[k][2]] + [subs[e][1]]
            runs.append(np.asarray(points, float))
        kept = sum(float(np.linalg.norm(subs[k][1][:2]-subs[k][0][:2])) for s, e in ranges for k in range(s, e+1))
        self.air_skipped += sum(float(np.linalg.norm(s[1][:2]-s[0][:2])) for s in subs) - kept
        return runs

    def skips_air(self, state):
        """Whether surface paths may be cut short where they cross cleared ground.

        Only 3D Pocket (waterfall) paths may be cut short, reordered or sent to a
        new place: 3D Contour lines are followed from end to end, in order (it
        may lift at the end of a line to go back to the start of the next).
        """
        return self.skip_air and state is not None and getattr(self.config, 'kind', None) != 'contour3d'

    def surface_layer(self, paths):
        """One XYZ depth band: drop air, then visit the remaining pieces nearest-first.

        Splitting raster lines at cleared stretches leaves pieces at both ends of
        many lines; visiting them in raster order would rapid back and forth across
        the cleared middle. Pieces keep their cutting direction. Air is judged on
        the material before the band, which stays valid: material only decreases.
        """
        state = self.material.height if self.material.height is not None else self.material.estimate_height()
        if not self.skips_air(state):
            for n, pts in enumerate(paths):
                self._surface_run(state, pts, last=n == len(paths)-1)
            return
        runs = []
        for pts in paths:
            pieces = self._material_runs(state, pts)
            if not pieces:
                self.air_paths += 1
                self.air_skipped += float(np.linalg.norm(np.diff(pts[:, :2], axis=0), axis=1).sum())
            runs.extend(pieces)
        order = _nearest_order(runs, self.position[:2])
        for n, k in enumerate(order):
            self._surface_run(state, runs[k], last=n == len(order)-1)

    def surface_path(self, pts, last=True):
        """XYZ surface path, skipping stretches already cleared by earlier moves or tools."""
        state = self.material.height if self.material.height is not None else self.material.estimate_height()
        if not self.skips_air(state):
            return self._surface_run(state, pts, last=last)
        runs = self._material_runs(state, pts)
        if not runs:
            self.air_paths += 1
            self.air_skipped += float(np.linalg.norm(np.diff(pts[:, :2], axis=0), axis=1).sum())
        for n, run in enumerate(runs):
            self._surface_run(state, run, last=last and n == len(runs)-1)

    # ------------------------------------------------- leads: one rule for every path
    def _lead_mode(self, which):
        from gcodeproducer.core.cam.operation import Operation
        return Operation.lead_mode(getattr(self.config, which, False)) if self.config is not None else "none"

    def wants_lead_in(self):
        """Lead-in mode: every entry, the first entry of each layer, or none."""
        mode = self._lead_mode("lead_in")
        return mode == "every" or (mode == "layer" and not self._layer_entered)

    def wants_lead_out(self, last):
        """Lead-out mode: every exit, the last exit of each layer, or none."""
        mode = self._lead_mode("lead_out")
        return mode == "every" or (mode == "layer" and last)

    def lead_in(self, state, pts, closed, length, top=None):
        """The shared lead for a flat or surface path: (N,3) ramp or None, with its warning / count."""
        return self.lead_kind(*self.entries.entry(state, pts, closed, length, top, self.name))

    def lead_kind(self, lead, kind):
        if kind == "degenerate":
            warning = f"{self.name}: zero-length path; vertical entry used. Confirm the tool can plunge."
            if warning not in self.job.warnings:
                self.job.warnings.append(warning)
            self.ctx.log("LEAD WARNING: "+warning)
            return None
        if kind in ("helix", "zigzag"):
            self.lead_kinds[kind] = self.lead_kinds.get(kind, 0)+1
        return lead

    def ramp_in(self, state, lead):
        for q in lead[1:]:
            self.feed_move(q, "lead_in", state, comment="lead-in along the path", split=True)

    def lead_out(self, state, pts, closed, length):
        """The shared exit: on forward from the end at the cutting feed, climbing at the lead-out angle.

        Only over space already cleared: around a closed path that is its own
        cut; straight on from an open path it must be checked. If any of the
        exit would meet material (an open path ending at a wall - a slot), or
        the material is unknown for an open path, there is no lead-out and the
        tool retracts straight out.
        """
        exit_points = self.entries.exit(pts, closed, length)
        if exit_points is None:
            return
        if (state is None and not closed) or (state is not None and any(
                state.contact(a, b, self.radius) for a, b in zip(exit_points, exit_points[1:]))):
            self.lead_outs_skipped += 1
            return
        for q in exit_points[1:]:
            if not self.feed_move(q, "lead_out", state, comment="lead-out along the cleared path", split=True,
                                  cleared_only=True):
                self.ctx.log(f"  {self.name}: lead-out crosses uncertain remaining cells; retracting instead")
                break

    def _surface_run(self, state, pts, last=True):
        """XYZ surface path: shared entry, lead-in only into material, measured cuts, cleared lead-out."""
        config = self.config
        length = (config.lead_length if config is not None else 0) or 2*self.radius
        lead = self.lead_in(state, pts, False, length) if self.wants_lead_in() else None
        approach = lead[0] if lead is not None else pts[0]
        self._path_cut_material = False
        self.enter(state, approach[:2], approach[2], lead is not None)
        self._layer_entered = True
        if lead is not None:
            self.ramp_in(state, lead)
        self._surface_cut = True
        for q in pts[1:]:
            self.feed_move(q, "cut", state, split=True)
        self._surface_cut = False
        if self.wants_lead_out(last) and self._path_cut_material:
            self.lead_out(state, pts, False, length)

    def planar_path(self, layer, path_index, path, previous_end):
        """XY path at the layer depth: link or entry, leads, planned cuts, cleared lead-out."""
        live, config, name, job = self.material.height, self.config, self.name, self.job
        pts = np.asarray(path.points, float)
        loop = np.vstack([pts, pts[0]]) if path.closed else pts
        start = loop[0]
        length = (config.lead_length if config is not None else 0) or 2*self.radius
        self._path_cut_material = False
        linked = self.links.linked(path, previous_end)
        floor = float(format_number(layer.z, 3))
        route = None if linked else self.cleared_planar_route(live, layer, path_index, floor)
        if linked:
            self.feed_move(np.r_[start, self.position[2]], "link", live, path.link_condition,
                           "stay-down link", measured=False, force_feed=True)
        elif route is not None:
            if any(np.linalg.norm(point-self.position[:2]) > 1e-9 for point in route):
                self.stay_count += 1
            for point in route:
                self.travel_at_depth(point)
        else:
            flat = np.column_stack((pts[:, :2], np.full(len(pts), float(layer.z))))
            want = self.wants_lead_in() and len(pts) > 1
            lead, kind = self.entries.entry(live, flat, path.closed, length, name=name) if want else (None, None)
            stayed = False
            if config is not None and live is not None:
                here = self.position[2]
                down, down_kind = (self.entries.entry(live, flat, path.closed, length, top=here, name=name)
                                   if want and layer.z+1e-9 < here < self.safe_z-1e-9 else (None, None))
                target = down[0, :2] if down is not None else start
                if here > floor+1e-9 and self.links.stay_at_depth(live, self.position, target, floor):
                    lead, kind, stayed = down, down_kind, True
                    self.travel_at_depth(target)
                    self.stay_count += 1
            lead = self.lead_kind(lead, kind)
            approach = lead[0, :2] if lead is not None else start
            entry = lead[0, 2] if lead is not None else layer.z
            if stayed:
                self.descend(live, approach, entry)
            else:
                self.enter(live, approach, entry, lead is not None)
            self._layer_entered = True
            if lead is not None:
                self.ramp_in(live, lead)
        first_cut = not linked     # an entry always restates the cutting feed
        for i, q in enumerate(loop[1:]):
            condition = path.cut_conditions[i] if i < len(path.cut_conditions) else None
            self.feed_move(np.r_[q, self.position[2]], "cut", live, condition, measured=False, force_feed=first_cut)
            first_cut = False
        next_path = layer.paths[path_index+1] if path_index+1 < len(layer.paths) else None
        if (self.wants_lead_out(next_path is None) and len(pts) > 1 and not (next_path and next_path.stay_down)
                and (live is None or self._path_cut_material or not path.cut_conditions
                     or any(c.engagement > 1e-6 for c in path.cut_conditions))
                and not (next_path and self.cleared_planar_route(live, layer, path_index+1, floor) is not None)):
            self.lead_out(live, np.column_stack((pts[:, :2], np.full(len(pts), self.position[2]))), path.closed, length)
        return self.position[:2].copy()

    def cleared_planar_route(self, state, layer, index, floor):
        from .planner_constants import INWARD_ROUTE_SAMPLE_PATHS, INWARD_ROUTE_SAMPLES

        if state is None or not self.links.short_retracts or abs(self.position[2]-floor) > 1e-9:
            return None
        path = layer.paths[index]
        if path.feature == 'drill' or len(path.points) < 2 or len(path.points[0]) != 2:
            return None
        target = np.asarray(path.points[0], float)
        if self.links.stay_at_depth(state, self.position, target, floor):
            return (target,)
        if not index or self.config is None or self.config.strategy != 'adaptive' or not self.config.stay_down:
            return None
        samples = []
        for p in layer.paths[max(0, index-INWARD_ROUTE_SAMPLE_PATHS):index]:
            pts = np.asarray(p.points, float)
            if len(pts) and pts.shape[1] == 2:
                samples.append(pts[np.linspace(0, len(pts)-1, min(len(pts), INWARD_ROUTE_SAMPLES), dtype=int)])
        if not samples:
            return None
        waypoint = self.links.inward_waypoint(state, self.position, target, np.vstack(samples))
        return None if waypoint is None else (waypoint, target)

    # ----------------------------------------------------------------- loop
    def run(self, first_tool, first_data):
        from gcodeproducer.core.cam.cutting import resolve_cutting
        from .engagement_model import EngagementModel
        job, ctx = self.job, self.ctx
        tool_map = {t.id: t for t in job.tools}
        tool = first_tool
        feed = tool.get("feed", 800) if tool else job.m("max_feed", 800)
        plunge = tool.get("plunge_feed", 300) if tool else 300
        lead = plunge
        rpm = self.rpm
        data = first_data
        rate_key = None
        previous_group = getattr(job.layers[0], "cam_group", None) if job.layers else None
        from .move_estimate import estimate_cut_segments
        estimated = estimate_cut_segments(job.layers, tool_map, first_tool, self.material.height,
                                          self.sample_spacing)
        ctx.log(f'  CAM estimate: ~{estimated:,} sampled cut segments (before merging; entries, exits '
                'and links not included)')
        n = max(1, len(job.layers))
        for li, layer in enumerate(job.layers):
            key = getattr(layer, "cam_operation_key", None)
            name = getattr(layer, "cam_operation", None)
            self.layer, self.name = li, name
            self.op = f"{key[0]+1}.{key[1]+1} {name}" if key is not None else name
            group = getattr(layer, "cam_group", None)
            starts_file = group != previous_group and not self.auto_tool_change
            if not starts_file:
                self.comment(f"LAYER:{li}")
            next_tool = tool_map.get(getattr(layer, "cam_tool_id", None), tool)
            config = self.config = getattr(layer, "cam_operation_config", None)
            previous_data = data
            data = getattr(layer, "cam_cutting", None) or (resolve_cutting(job.machine, next_tool, self.stock, config)
                                                          if next_tool else None)
            if group != previous_group:
                self.rapid_z(self.safe_z)
                spindle = format_number(data.rpm if data else next_tool.get('spindle_rpm', 18000), 0)
                if self.auto_tool_change:
                    self.command("M5", "spindle off before tool change")
                    self.command(f"T{int(next_tool.get('tool_number', 1))} M6")
                else:
                    # Manual changer: the writer closes this file (end G-code) and opens the
                    # next one (start G-code). Re-establish safe Z after an unknown start block.
                    self.add("split", payload=(tool, previous_data, next_tool, data))
                    self.comment(f"LAYER:{li}")    # the layer marker belongs to the new file
                    self.rapid_z(self.safe_z, comment="safe height after start G-code")
                    self.files += 1
                self.command(f"M3 S{spindle}")
                rpm = data.rpm if data else rpm
                previous_group = group
            tool = self.tool = next_tool
            self.radius = float(tool.get("diameter", 0))/2 if tool else 0.
            self.entries = EntryExitPlanner(self.safe_z, self.lead_clearance, self.radius,
                                            getattr(config, 'lead_angle', RAMP_ANGLE),
                                            getattr(config, 'lead_out_angle', 0.))
            self.links = LinkPlanner(self.safe_z, self.travel_clearance, self.lead_clearance, self.short_retracts, self.radius)
            self.model = EngagementModel(config, tool, self.machine)
            if data and (li == 0 or data.rpm != rpm):
                self.command(f"M3 S{format_number(data.rpm, 0)}", "calculated / overridden RPM")
            rpm = data.rpm if data else rpm
            feed = self.feed = data.feed if data else (tool.get("feed", 800) if tool else feed)
            plunge = self.plunge = data.plunge if data else feed*float(self.machine.get(*PLUNGE_FEED_FIELD))/100
            lead = self.lead = data.lead_feed if data else (tool.get("plunge_feed", 300) if tool else lead)
            current = (group, name, rpm, feed, lead, plunge)
            if current != rate_key:
                ctx.log(f"  {name or 'CAM'}: {data.material if data else 'legacy'} • {rpm:g} rpm • "
                        f"cut base {feed:g} • lead base {lead:g} • plunge {plunge:g} mm/min")
                rate_key = current
            if hasattr(layer, "cam_operation"):
                self.comment(f"Operation: {layer.cam_operation}")
            previous_end = None   # never carry stay-down permission across depth/operation/tool boundaries
            self._layer_entered = False   # lead-in "Layer entry": only the first entry of each layer ramps
            surface = [np.asarray(p.points, float) for p in layer.paths]
            if surface and all(len(p) >= 2 and p.shape[1] == 3 for p in surface):
                self.surface_layer(surface)
                ctx.progress((li + 1) / n)
                continue
            for path_index, path in enumerate(layer.paths):
                pts = np.asarray(path.points, float)
                if len(pts) < (1 if path.feature == "drill" else 2):
                    continue
                if pts.shape[1] == 3:
                    self.surface_path(pts, last=path_index == len(layer.paths)-1)
                    previous_end = None
                else:
                    previous_end = self.planar_path(layer, path_index, path, previous_end)
            ctx.progress((li + 1) / n)
        self.tool, self.data = tool, data
        self.plan.finish()
        self.report()
        if not self.auto_tool_change and self.files > 1:
            self.ctx.log(f'  Manual tool changes: output split into {self.files} files, one per tool group')
        self.ctx.log(f'  CAM planned {self.samples:,} sampled feed segments; '
                     f'{self.plan.total:,} program segments written')
        return self.plan

    def report(self):
        ctx = self.ctx
        if self.stay_count:
            ctx.log(f"  {self.stay_count} entries moved across cleared material at depth (no retract)")
        if self.short_count:
            ctx.log(f"  {self.short_count} entries used short retracts above current material instead of safe Z")
        if self.lead_outs_skipped:
            ctx.log(f"  {self.lead_outs_skipped} lead-outs skipped: carrying on would meet material (e.g. a slot "
                    "ending at a wall); retracted straight out instead")
        for kind, count in sorted(self.lead_kinds.items()):
            what = "circling the closed contour" if kind == "helix" else "back and forth along the open path"
            ctx.log(f"  {count} lead-in ramps longer than their path: {kind} ({what}) at <=10 degrees")
        if self.air_skipped > 0:
            ctx.log(f"  Remove air cutting: skipped {self.air_skipped:,.0f} mm of 3D moves through material "
                    f"already cleared by earlier passes or tools ({self.air_paths} whole paths)")
        if self.surface_totals:
            ctx.log("  3D engagement moves: " + ", ".join(f"{kind}={self.surface_totals[kind]}"
                    for kind in ("slot", "high", "cut", "hsm", "air")))
        for request, cap in sorted(self.policy.capped):
            ctx.log(f"  CAM feed capped: {request:g} -> {cap:g} mm/min (machine max_feed)")
