"""Display options shared by the viewers + colour computation."""
from __future__ import annotations

import math

import numpy as np
from PyQt6.QtCore import QObject, pyqtSignal

from ..core.features import feature_color
from ..core.toolpath import CUT, EXTRUDE, RAPID, SOLID_KINDS, TRAVEL, Toolpath

COLOR_MODES = [("feature", "Feature type"), ("type", "Move type"), ("speed", "Speed / feed"),
               ("layer", "Layer"), ("changes", "Changes"), ("operation", "Operation (CAM)"),
               ("engagement", "Tool engagement (CAM)")]

KIND_COLORS = {EXTRUDE: (1.0, 0.55, 0.15), TRAVEL: (0.35, 0.65, 1.0), CUT: (1.0, 0.75, 0.2), RAPID: (1.0, 0.25, 0.25)}
TRAVEL_COLOR = (0.35, 0.65, 1.0)
RAPID_COLOR = (1.0, 0.3, 0.3)
CHANGED_COLOR = (1.0, 0.1, 0.9)
UNCHANGED_COLOR = (0.42, 0.42, 0.45)

_RAMP = np.array([[0.1, 0.2, 0.9], [0.0, 0.8, 0.9], [0.1, 0.85, 0.2], [1.0, 0.9, 0.0], [1.0, 0.15, 0.1]], np.float32)


def op_color(name: str) -> tuple:
    """Colour of a CAM operation (stable per name)."""
    return feature_color(f"op:{name}") if name else (0.6, 0.6, 0.6)


def ramp(t: np.ndarray) -> np.ndarray:
    t = np.clip(np.nan_to_num(t), 0.0, 1.0) * (len(_RAMP) - 1)
    i = np.minimum(t.astype(int), len(_RAMP) - 2)
    f = (t - i)[:, None]
    return _RAMP[i] * (1 - f) + _RAMP[i + 1] * f


class ViewState(QObject):
    #: 'colors' -> colours must be recomputed, 'view' -> repaint only
    changed = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.color_mode = "feature"
        self.hidden_features: set = set()
        self.hidden_ops: set = set()        # CAM operations hidden in the viewer
        self.show_extrude = True
        self.show_travel = False
        self.show_retracts = True
        self.show_tool = True
        self.show_grid = True
        self.dim_lower = False
        self.width = 0.45
        self.layer_min = 0
        self.layer_max = 1 << 30
        self.speed_range = None  # (lo, hi) mm/min for comparable colouring
        # section plane
        self.section = False
        self.section_axis = "Z"
        self.section_yaw = 0.0
        self.section_pitch = 0.0
        self.section_offset = 0.0
        self.section_flip = False
        self.section_slab = 0.0
        self.section_show_plane = True

    def set(self, what: str = "view", **kw) -> None:
        for k, v in kw.items():
            setattr(self, k, v)
        self.changed.emit(what)

    # ------------------------------------------------------------ section
    def section_normal(self) -> np.ndarray:
        a = self.section_axis
        if a == "X":
            n = np.array([1.0, 0, 0])
        elif a == "Y":
            n = np.array([0, 1.0, 0])
        elif a == "Z":
            n = np.array([0, 0, 1.0])
        else:
            y, p = math.radians(self.section_yaw), math.radians(self.section_pitch)
            n = np.array([math.cos(p) * math.cos(y), math.cos(p) * math.sin(y), math.sin(p)])
        return -n if self.section_flip else n

    def section_plane(self) -> np.ndarray:
        """vec4 (n, d): points with dot(n,p) - d > 0 are cut away."""
        n = self.section_normal()
        d = self.section_offset * (-1 if self.section_flip else 1)
        return np.array([n[0], n[1], n[2], d], np.float32)

    # ------------------------------------------------------------- colours
    def segment_colors(self, tp: Toolpath) -> np.ndarray:
        n = len(tp.kind)
        col = np.empty((n, 4), np.float32)
        col[:, 3] = 1.0
        solid = np.isin(tp.kind, SOLID_KINDS)
        mode = self.color_mode
        if mode == "feature":
            pal = np.array([feature_color(f) for f in tp.feature_names] or [(1, 1, 1)], np.float32)
            col[:, :3] = pal[tp.feature]
        elif mode == "type":
            for k, c in KIND_COLORS.items():
                col[tp.kind == k, :3] = c
        elif mode == "speed":
            lo, hi = self.speed_range or self.feed_range(tp)
            col[:, :3] = ramp((tp.feed - lo) / max(hi - lo, 1e-6))
        elif mode == "layer":
            col[:, :3] = ramp(tp.layer / max(1, tp.num_layers - 1))
        elif mode == "operation":
            names = tp.op_names or [""]
            pal = np.array([op_color(nm) for nm in names], np.float32)
            col[:, :3] = pal[tp.op] if tp.op is not None and len(tp.op) else (0.6, 0.6, 0.6)
        elif mode == "engagement":
            e = tp.engagement if tp.engagement is not None else np.full(n, np.nan, np.float32)
            col[:, :3] = ramp(e)
            col[np.isnan(e), :3] = (0.35, 0.35, 0.38)
        elif mode == "changes":
            ch = tp.line_changed[tp.line] if len(tp.line_changed) else np.zeros(n, bool)
            col[:, :3] = UNCHANGED_COLOR
            col[ch, :3] = CHANGED_COLOR
        if mode not in ("type", "changes"):
            col[tp.kind == TRAVEL, :3] = TRAVEL_COLOR
            col[tp.kind == RAPID, :3] = RAPID_COLOR
        # visibility in alpha
        vis = np.where(solid, self.show_extrude, self.show_travel)
        if self.hidden_features:
            hidden_ids = [i for i, f in enumerate(tp.feature_names) if f in self.hidden_features]
            if hidden_ids:
                vis &= ~(np.isin(tp.feature, hidden_ids) & solid)
        if self.hidden_ops and tp.op is not None and len(tp.op):
            hidden_ids = [i for i, nm in enumerate(tp.op_names) if nm in self.hidden_ops]
            if hidden_ids:
                vis &= ~np.isin(tp.op, hidden_ids)
        col[:, 3] = vis.astype(np.float32)
        return col

    @staticmethod
    def feed_range(tp: Toolpath):
        solid = np.isin(tp.kind, SOLID_KINDS) & (tp.feed > 0)
        if not solid.any():
            return 0.0, 1.0
        f = tp.feed[solid]
        return float(np.percentile(f, 1)), float(np.percentile(f, 99))
