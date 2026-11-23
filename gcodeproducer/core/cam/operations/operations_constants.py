"""Operation-kind registry: kind -> generator class (module, class name)."""

GENERATORS = {
    "pocket": ("pocket_generator", "PocketGenerator"),
    "profile": ("profile_generator", "ProfileGenerator"),
    "slot": ("open_path_generator", "OpenPathGenerator"),
    "engrave": ("open_path_generator", "OpenPathGenerator"),
    "drill": ("drill_generator", "DrillGenerator"),
    "waterfall": ("waterfall_generator", "WaterfallGenerator"),
    "contour3d": ("contour3d_generator", "Contour3dGenerator"),
}
# Adaptive Waterfall following the surface: passes stepping up the slope between depths.
SLOPE_STEP_MIN = .1  # mm; least step between them
SLOPE_PASSES = 200  # most of them at one depth
