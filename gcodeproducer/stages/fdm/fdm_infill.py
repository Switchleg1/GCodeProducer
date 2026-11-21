"""FDM stage: sparse infill inside each layer using the selected pattern.

Fills the region inside the innermost perimeter, skipping any cells already
claimed by the top / bottom solid shells (so sparse and solid never overlap).
"""
from __future__ import annotations

from gcodeproducer.stages.fdm.fdm_constants import FDMINFILL_PARAMS
import numpy as np, gcodeproducer.core.geometry.infill as infill_gen
from gcodeproducer.core.jobs.path import Path
from dataclasses import replace
from gcodeproducer.core.fdm.bridges import exclude_bridges
from gcodeproducer.core.fdm.fdm_constants import GAP_CLIPPED_FEATURES
from gcodeproducer.core.fdm.layer_threads import layer_map
from gcodeproducer.core.fdm.wall_regions import slice_region
import shapely
from shapely.geometry import Polygon
from gcodeproducer.core.fdm.gap_fill import clip_segments, gap_beads, gap_regions, infill_area, small_islands
from gcodeproducer.stages.base.api import AUTO, FDM
from gcodeproducer.stages.base.slice_stage import SliceStage


class FDMInfill(SliceStage):
    id = "fdm_infill"
    name = "Infill"
    description = "Fill the region inside the innermost perimeter with a pattern (sparse)."
    workflows = (FDM,)
    category = "Infill"
    params = FDMINFILL_PARAMS

    def run(self, job, params, ctx):
        job.settings["optimize_mixed_infill"] = params["optimize_mixed_infill"]
        density = params["density"] / 100.0
        solid_islands = params["solid_island_area"] if params["solid_islands"] else 0.
        if density <= 0 and not params["gap_fill"] and solid_islands <= 0:
            return "infill off"
        lw = params["line_width"]
        lw = job.settings.get("perimeter_line_width", job.line_width) if lw in (0, AUTO) else float(lw)
        spacing = lw / max(density, 1e-3)
        pattern = params["pattern"]
        angle = params["angle"]
        inset = lw * 0.5 * (1.0 - params["overlap"] / 100.0)

        gap_fill = params["gap_fill"]
        wall_lw = job.settings.get("perimeter_line_width", job.line_width)
        gap_width = params["gap_fill_width"]
        gap_width = 2 * wall_lw if gap_width in (0, AUTO) else float(gap_width)
        min_width = job.settings.get("min_bead_width", lw * 0.5)
        max_width = job.settings.get("max_bead_width", lw * 1.5)
        gap_overlap = lw * 0.5 * params["overlap"] / 100.0

        def work(layer):
            regions = [np.asarray(c, float) for c in layer.contours if len(c) >= 3]
            if not regions:
                return None
            segs_all = []
            if density > 0:
                block = layer.solid_mask            # RegionMask of solid cells, or None
                inner = slice_region(layer.contours).buffer(-inset)
                for phi, period, off in infill_gen.pattern_families(pattern, layer.index, layer.z,
                                                                    spacing, angle):
                    s = infill_gen.scan_fill(regions, phi, period, off, inset, params["min_length"])
                    s = infill_gen.clip_to_region(s, inner, params["min_length"])
                    if block is not None and len(s):
                        s = infill_gen.split_by_raster(s, block, params["min_length"])
                    s = exclude_bridges(s, layer.bridge_region, params['min_length'])
                    if len(s):
                        segs_all.append(s)
            segs = np.concatenate(segs_all) if segs_all else np.zeros((0, 2, 2))
            paths, beads = None, []
            if gap_fill or solid_islands > 0:
                segs, paths, beads = self._gap_fill(layer, segs, wall_lw, lw, gap_width if gap_fill else 0.,
                                                    (min_width, max_width), gap_overlap, params["min_length"],
                                                    solid_islands)
            if len(segs) and params["connect"]:
                segs = infill_gen.order_segments(segs, start=(0.0, 0.0))
            return segs, paths, beads

        total = gaps_total = island_total = 0
        n = max(1, len(job.layers))
        for i, (layer, result) in enumerate(zip(job.layers, layer_map(work, job.layers))):
            if result is not None:
                segs, paths, beads = result
                if paths is not None:
                    layer.paths[:] = paths
                for feature, (points, widths, closed) in beads:
                    layer.paths.append(Path(feature, points, closed=closed, width=lw, widths=widths))
                    gaps_total += feature == "gap_fill"
                    island_total += feature != "gap_fill"
                for p0, p1 in segs:
                    layer.paths.append(Path("infill", np.array([p0, p1]), closed=False, width=lw))
                    total += 1
            ctx.progress((i + 1) / n)
        gaps = f", {gaps_total} gap-fill paths" if gap_fill else ""
        if solid_islands > 0:
            gaps += f", {island_total} solid small-island loops (< {solid_islands:g} mm²)"
        if density <= 0:
            return f"infill off{gaps}"
        return f"{total} infill lines ({params['density']:.0f}% {pattern}){gaps}"

    @staticmethod
    def _gap_fill(layer, segs, wall_lw, lw, gap_width, bead_range, overlap, min_length, island_area=0.):
        """Gap-fill / small-island beads, the fill segments outside them and the layer paths
        with trimmed solid lines.

        Returns ``(segs, paths or None, [(feature, bead), ...])``; reads the layer but does not
        change it. ``gap_width`` 0 skips thin gaps; ``island_area`` > 0 fills every layer island
        (outline piece) smaller than that many mm² completely with concentric perimeters.
        """
        area = infill_area(layer.contours, wall_lw)
        if area.is_empty:
            return segs, None, []
        gaps = gap_regions(area, gap_width, lw, blocked=layer.bridge_region) if gap_width > 0 else Polygon()
        islands, pieces = small_islands(layer.outline, area, island_area) if island_area > 0             else (Polygon(), Polygon())
        if not islands.is_empty:
            gaps = gaps.difference(islands)
        # fill lines must stay off the beads, which grow by the overlap into the walls,
        # and off the whole small island (its walls included)
        clip = shapely.union_all([gaps.buffer(overlap) if overlap > 0 else gaps, pieces])
        if clip.is_empty:
            return segs, None, []
        paths = None
        solid = [p for p in layer.paths if p.feature in GAP_CLIPPED_FEATURES and len(p.points) == 2]
        if solid:
            # solid lines come after walls and bridges, so their relative order is unchanged
            paths = [p for p in layer.paths if not (p.feature in GAP_CLIPPED_FEATURES and len(p.points) == 2)]
            for path in solid:
                for part in clip_segments(np.asarray([path.points], float), clip, min_length):
                    paths.append(replace(path, points=part))
        beads = [("gap_fill", b) for b in gap_beads(gaps, area, lw, *bead_range, overlap)]
        beads += [("solid_infill", b) for b in gap_beads(islands, area, lw, *bead_range, overlap)]
        return clip_segments(segs, clip, min_length), paths, beads
