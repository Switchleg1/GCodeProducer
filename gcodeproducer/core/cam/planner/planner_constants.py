"""Motion phases and the shared feed / feature rules of the CAM motion planner.

Phase says *why* the tool moves; a CutCondition says *how much material* it
meets. Both are kept on every motion segment (a lead-in is normally slotting).
"""

PHASES = ("rapid", "travel", "approach", "plunge", "lead_in", "link", "cut", "lead_out")
NON_MOTION = ("comment", "command")      # program lines planned without motion

# Phases fed from the lead / plunge base rate; everything else uses the cut base.
LEAD_BASE_PHASES = frozenset(("approach", "plunge", "lead_in", "lead_out"))

# Phases whose rate is scaled by the measured engagement band factor.
# A vertical plunge keeps its plunge rate; a verified-air approach is unscaled.
FACTOR_PHASES = frozenset(("lead_in", "link", "cut", "lead_out"))

# Phases with their own Preview feature colour, independent of engagement.
PHASE_FEATURES = {"approach": "air", "plunge": "plunge", "lead_in": "lead_in", "lead_out": "lead_out"}

ENGAGEMENT_FEATURES = {"slot": "slot", "high": "high_engagement", "cut": "cut", "hsm": "hsm", "air": "air"}

MIN_FEED = .0001             # mm/min: smaller effective feeds cannot be represented safely
# Split sub-moves of these phases may be written as one G1. Lead-ins and
# plunges stay separate so the replayed entry-depth checks keep their spans.
MERGE_PHASES = frozenset(("cut", "link", "lead_out"))
MOTION_CHUNK_SIZE = 4096     # flush serialized motion without keeping the full plan in RAM
ENGAGED = 1e-6               # engagement above this counts as material contact
SETTLE_PASSES = 3            # planar lead start-height settling iterations
