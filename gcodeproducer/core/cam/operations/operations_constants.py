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
# Waterfall surface following: dips in a lifted path shorter than this are filled
# (raise only), so height-grid noise does not saw the cutter up and down.
FOLLOW_SMOOTH = .5  # mm
