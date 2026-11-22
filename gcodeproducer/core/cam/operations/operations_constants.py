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
FOLLOW_MIN_LENGTH = .2  # mm; shorter surface-following pieces between Waterfall depths are dropped
