"""Motion phases and the shared feed / feature rules of the CAM motion planner.

Phase says *why* the tool moves; a CutCondition says *how much material* it
meets. Both are kept on every motion segment (a lead-in is normally slotting).
"""

PHASES = ("rapid", "travel", "approach", "plunge", "lead_in", "link", "cut", "lead_out")
NON_MOTION = ("comment", "command", "split")  # program lines planned without motion; split = new file

# Phases fed from the lead-in base rate; plunges (and any engaged descent steeper
# than the lead-in ramp) use the plunge rate; everything else uses the cut base.
# A lead-out carries on at the cutting feed so the speed does not change at the wall.
LEAD_BASE_PHASES = frozenset(("approach", "lead_in"))

# Phases whose rate is scaled by the measured engagement band factor.
# A vertical plunge keeps its plunge rate; a verified-air approach is unscaled.
FACTOR_PHASES = frozenset(("lead_in", "link", "cut", "lead_out"))

# Phases with their own Preview feature colour, independent of engagement.
PHASE_FEATURES = {"approach": "air", "plunge": "plunge", "lead_in": "lead_in", "lead_out": "lead_out"}

ENGAGEMENT_FEATURES = {"slot": "slot", "high": "high_engagement", "cut": "cut", "hsm": "hsm", "air": "air"}

# Feeds for descents into material are blended by angle in this many steps per
# span (cut -> lead-in up to the lead-in angle, lead-in -> plunge up to vertical),
# so successive sub-moves of nearly equal angle share one rate and still merge.
DESCENT_FEED_STEPS = 20
# Consecutive moves of these phases form one run for feed smoothing (FeedSmoother).
FEED_SMOOTH_PHASES = frozenset(("cut", "link", "lead_in", "lead_out"))
MIN_FEED = .0001             # mm/min: smaller effective feeds cannot be represented safely
# Split sub-moves of these phases may be written as one G1. Lead-ins and
# plunges stay separate so the replayed entry-depth checks keep their spans.
MERGE_PHASES = frozenset(("cut", "link", "lead_out"))
# XYZ air stretches longer than this many cutter diameters are replaced by a
# retract and re-entry; shorter ones are fed through (cheaper than retracting).
AIR_GAP_DIAMETERS = 2.
# Rapid/clearance checks widen the cutter by this much: emitted coordinates are
# rounded to 0.001 mm, which can move a grid cell from just outside to inside.
CLEARANCE_MARGIN = .002
INWARD_ROUTE_CANDIDATES = 16
INWARD_ROUTE_SAMPLE_PATHS = 4
INWARD_ROUTE_SAMPLES = 16
INWARD_ROUTE_DETOUR_DIAMETERS = 4.
MOTION_CHUNK_SIZE = 4096     # flush serialized motion without keeping the full plan in RAM
ENGAGED = 1e-6               # engagement above this counts as material contact
SETTLE_PASSES = 8            # lead start-height settling iterations (flat and surface paths)
