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
SLOPE_JOIN_STEPS = 3.  # a slope pass joins the one before when it starts within this many steps of its end
SLOPE_AIR = .01  # mm; a slope pass riding this close to the depth above is in air the pass above cleared
SLOPE_SLANT = 3.  # steps along the next slope pass it is joined at when there is no room to turn round onto its start
ADAPTIVE_STEP_UPS = 3  # adaptive step-up levels between two depths when following the surface (stairs a quarter of the step)
STEP_UP_TALL_MARGIN = .05  # mm kept from stock that stands above the depth above a step-up level
