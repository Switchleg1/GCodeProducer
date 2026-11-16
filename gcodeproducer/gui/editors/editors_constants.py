"""Shared editor choices and operation-override bindings."""

REFERENCE_DRAW_MODES = (
    ("Circle — center then rim", "circle", "center", "center", "point on the circle"),
    ("Circle — diameter endpoints", "circle", "edge", "first diameter endpoint", "opposite diameter endpoint"),
    ("Rectangle — center then corner", "rectangle", "center", "center", "corner"),
    ("Rectangle — opposite corners", "rectangle", "edge", "first corner", "opposite corner"),
)

RATE_FIELDS = {
    "rpm": ("Spindle RPM", 100000, "unlock_rpm"),
    "feed": ("Normal cut base feed", 50000, "unlock_feed"),
    "lead_feed": ("Lead / plunge base feed", 50000, "unlock_lead_feed"),
}

STAGE_SUMMARY_TEMPLATES = {
    "fdm_perimeters": "{perimeters} loops",
    "fdm_top_bottom": "top {top_layers}, bottom {bottom_layers}",
    "fdm_infill": "{density:g}% {pattern}",
    "fdm_support": ("{density:g}% {pattern}, gap {z_gap_layers}/{bottom_z_gap_layers}, "
                    "interface {interface_layers}/{bottom_interface_layers}"),
    "fdm_emit": ("walls {outer_wall_speed:g}/{inner_wall_speed:g}, infill {infill_speed:g}, "
                 "travel {travel_speed:g} mm/s"),
}

DEPTH_SOURCES = (
    ("Model top + offset", "top"),
    ("Model bottom + offset", "bottom"),
    ("Absolute Z", "absolute"),
    ("Selected geometry + offset", "geometry"),
    ("Material surface + offset", "stock_top"),
    ("Machining selection + offset", "selection"),
)

PICK_MODES = (("Navigate / place model", ""), ("Select faces", "face"), ("Select edges", "edge"))

DEPTH_ROWS = (("start", "Start Z"), ("end", "End Z"))

OPERATION_SIDES = ("outside", "inside", "on")

CUT_DIRECTIONS = (("Climb", "climb"), ("Conventional", "conventional"), ("Meander", "meander"))

ENGAGEMENT_CONTROLS = (("low_engagement_feed", "HSM"),
                           ("standard_engagement_feed", "Cut"),
                           ("high_engagement_feed", "High engagement"),
                           ("slotting_feed", "Slot"))

TAB_DIRECTIONS = (("Outward from side wall", "auto"), ("To +X edge", "+x"), ("To -X edge", "-x"),
                           ("To +Y edge", "+y"), ("To -Y edge", "-y"))

TEMPLATE_BLOCK_SNIPPETS = (("{if ...}{endif} block", "{if chamber_temp > 0}\n{endif}"),
                               ("{if ...}{else}{endif} block", "{if heated_chamber}\n{else}\n{endif}"))

STOCK_FIELDS = (
            ("density", "Density", 0, 100, " g/cm³"),
            ("margin", "Auto margin (sides / bottom)", 0, 1000, " mm"),
            ("x", "Minimum X", -10000, 10000, " mm"),
            ("y", "Minimum Y", -10000, 10000, " mm"),
            ("top", "Surface Z", -10000, 10000, " mm"),
            ("width", "Width X", 0, 10000, " mm"),
            ("depth", "Depth Y", 0, 10000, " mm"),
            ("height", "Thickness Z", 0, 10000, " mm"),
        )
