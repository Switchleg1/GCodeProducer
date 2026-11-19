"""Shared settings constants and declarative tables."""
from __future__ import annotations
from gcodeproducer.core.parameters.param import Param

SCHEMA = [
    Param("fdm_travel_simplification", "float", 0.1, min=0, unit="mm", decimals=3, group="FDM travel",
          label="Travel waypoint simplification",
          help="Simplify the waypoints used to avoid open spaces. Paths are checked against the original "
               "outline, and detailed waypoints are tried if needed. 0 uses detailed waypoints only."),
    Param("skip_air_cuts", "bool", True, group="CAM toolpaths", label="Remove air cutting",
          help="Start each operation at the first depth that still holds material (estimated from earlier "
               "operations) and drop pocket contours that lie entirely in already-removed material. "
               "Off keeps every requested depth pass."),
    Param("short_retracts", "bool", True, group="CAM toolpaths", label="Short retracts within cleared material",
          help="Between entries, retract only to clearance above the CURRENT material along the travel (from the "
               "material simulation) and rapid down to the entry plane, instead of returning to safe Z and feeding "
               "down through air. Needs allocated stock. Fixtures/clamps are not modelled: turn off if they stand "
               "above the material."),
    Param("retract_clearance", "float", 1.0, min=.1, max=100, unit="mm", group="CAM toolpaths",
          label="Short retract clearance",
          help="With short retracts, rapid travels pass this far above the highest current material under the "
               "cutter along the move (never above safe Z)."),
    Param("lead_clearance", "float", .5, min=.05, max=50, unit="mm", group="CAM toolpaths",
          label="Lead-in start above material",
          help="A lead-in ramp starts this far above the current local material (the tool rapids down to "
               "there). The machine clearance Z still sets the height of short rapid travels."),
    Param("stock_resolution", "float", .2, min=.02, max=5, unit="mm", group="Material simulation",
          label="Material grid resolution",
          help="Height-field cell size for current-material checks, lead entry heights and the Material display. "
               "Finer grids catch smaller contacts but cost memory/time; the cell limit below can coarsen it."),
    Param("stock_max_cells", "int", 2_000_000, min=10_000, max=50_000_000, group="Material simulation",
          label="Maximum grid cells",
          help="Upper bound on height-field cells. When width x depth / resolution^2 exceeds it the grid is "
               "coarsened and a warning is issued."),
    Param("cam_surface_resolution", "float", 0., min=0, max=5, unit="mm", decimals=3,
          group="CAM planner resolution", label="3D surface grid",
          help="Cell size of the model height grid used by 3D Contour. 0 = auto: the material grid "
               "resolution, no coarser than tool diameter / 40 and no finer than 0.05 mm."),
    Param("cam_surface_tolerance", "float", .005, min=.001, max=1, unit="mm", decimals=3,
          group="CAM planner resolution", label="3D path tolerance",
          help="Maximum deviation when simplifying 3D Contour paths. Larger values write fewer points "
               "and can leave or remove up to this much more material along the surface."),
    Param("cam_engagement_step", "float", 0., min=0, max=50, unit="mm", decimals=3,
          group="CAM planner resolution", label="Engagement sample spacing",
          help="Length of each sub-move measured for engagement, feed and material removal on XYZ moves. "
               "0 = auto (half the tool radius, at least the material grid cell). Longer steps plan faster "
               "but average engagement over more distance."),
    Param("cam_merge_moves", "bool", True, group="CAM planner resolution",
          label="Combine same-condition feed moves",
          help="Write consecutive measured sub-moves of one straight move as a single G1 when phase, feed "
               "and engagement band match. Every sub-move is still measured and removes material."),
    Param("highlight_conflicts", "bool", True, group="Warnings", label="Colour conflicts and collisions",
          help="Recolour flagged moves as Conflict / Collision features in Feature colour mode."),
    Param("default_material_limit", "float", 0.0, min=-1000, max=1000, unit="mm", group="Default operation settings",
          label="Material boundary limit",
          help="Initial value for new operations. Where a pocket region reaches the blank edge, the cutter's outer "
               "edge may travel this far relative to that edge: 0 touches it, -1 leaves 1 mm of material, "
               "+1 lets the tool pass 1 mm beyond it."),
    Param("default_area_order", "choice", "area", group="Default operation settings",
          label="Area order", choices=[("area", "Each area to full depth"), ("depth", "Each depth across all areas")],
          help="Initial order for new operations with separate machining areas. Each area to full depth finishes "
               "one area before moving to the next; each depth visits all areas before stepping down."),
    Param("default_overcut", "float", 0.0, min=0, max=1000, unit="mm", group="Default operation settings",
          label="Overcut",
          help="Initial overcut for new Pocket and 3D Waterfall operations."),
]

MESSAGES = {
    "cam_warnings": "CAM material / engagement warnings after generation",
    "cam_stale_export": "CAM export blocked: regenerate paths",
    "cannot_slice": "Cannot slice / generate (setup error)",
    "slice_failed": "Slicing / generation failed",
    "auto_generate_failed": "Automatic support generation failed",
    "import_failed": "Model import failed",
    "no_model": "No model loaded",
    "no_machine": "No machine for this workflow",
    "outside_volume": "Model outside the build volume (continue without asking)",
    "delete_reference": "Confirm deleting reference geometry (unchecked: delete without asking)",
    "settings_save_failed": "Settings could not be saved",
    "opengl": "OpenGL errors",
}

DEFAULTS = {p.name: p.default for p in SCHEMA}

DEFAULTS["messages"] = {key: True for key in MESSAGES}
