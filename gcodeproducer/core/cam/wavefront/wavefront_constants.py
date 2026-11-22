"""Tuning of the wavefront pocket clearing; values are in mm and degrees unless named otherwise."""

CENTER_BUFFER_SEGMENTS = 64  # sides of a cutter-centre offset round a corner
STEPOVERS = (1., .8, .65, .5, .45, .4, .35, .3, .25, .2, .15, .12)
SWEEP_SEGMENTS = 16
CUT_SEGMENTS = 32  # keeps a cut's end cap within the link tolerance of a true disc
WALL_TOLERANCE = .02
CORNER_DEPTH = .3  # mm of stock a corner creep may meet at its deepest point
CORNER_TURN = 30.  # degrees of wall turn that make a corner worth creeping into
CORNER_RUN_IN = 8.  # mm of wall back from a corner where a creep may start
CORNER_STEPS = (2., 1., .4, .3, .2, .15, .1, .06)  # mm a corner creep goes deeper each time, tried in turn
SLIVER = 1e-3  # mm; half the thickness of a film of stock that is only polygon arithmetic
MIN_GAIN_MM2 = 1e-4
ELONGATED_ASPECT = 2.
NECK_RATIO = 2.  # a lobe is at least this much wider than the neck that separates it
HOLED_NECK_RATIO = 1.15  # the same round a boss
PROFILE_CHUNK = 8.  # mm of wall judged at a time
GLANCE_TURN = 40.  # degrees turned over a hook's length; more means the arc is curling onto an old hook
GLANCE_REACH = 6.  # mm of wall an arc may run on along before reaching clean wall
GLANCE_ANGLE = 55.  # degrees; an arc meeting the wall more squarely than this gets a hook
BOW_WIDTH_FACTOR = 2.6  # a channel narrower than this many full hook trims is crossed in one bow
BOW_SET_BACKS = 6  # tries at setting a bow back behind a curved front
BOW_EXCESS = .03  # mm a bow may stand out beyond its front
ROLL_STEPOVER = .35  # mm; at or below this an arc may roll off before the wall instead of sweeping it
SPAN_SLACK = .15  # cutter radii by which a spiral may miss the second wall and still span the channel
STEADY_STEPOVER = .4  # mm; from here up a refused larger stepover is not retried on every pass
RAISE_PATIENCE = 2  # passes at one stepover before a larger one is tried again
RAISE_PATIENCE_MAX = 8  # the wait doubles up to this each time the larger one is refused
BOW_PARALLEL = 8.  # degrees; walls further from parallel than this get separate hooks
HOOK_SHARE = .45  # share of the channel width each end of a bow may round
MIN_HOOK_TRIM = .5  # mm; below this an arc end rolls off to the old front instead
HOOK_SEARCH = 25.  # mm of arc searched back from the wall for a steady heading
HOOK_RADIUS_FACTOR = 2.0  # hook radius at the wall, in cutter radii
WALL_CORNER = 40.  # degrees of wall turning within CORNER_WINDOW that end a wall
CORNER_WINDOW = 2.  # mm
WALL_GAP = .8  # mm between cleared ground and the wall beyond which the wall is not followed
NEAR_WALL = .3  # mm; an arc end this close to the wall is carried onto it
WALL_REACH = 20.  # mm; farthest an arc end follows the wall back looking for clean wall
LINK_TOLERANCE = 1e-3  # mm; buffered arcs make the cleared region slightly approximate
LINK_HANDLE = 3.  # mm; longest handle of a link curve, so how widely it rounds a corner
LINK_HANDLE_SHARES = (.4, .25, .12)  # handle as a share of the leg, tried in turn
LINK_STEP = .5  # mm between points of a link curve
# Machine model for the time estimate only; nothing is written for a machine.
MACHINE_DEFAULTS = {'cut_feed_mm_min': 1500., 'link_feed_mm_min': 3000., 'plunge_feed_mm_min': 500.,
                    'rapid_mm_min': 5000., 'acceleration_mm_s2': 500., 'junction_deviation_mm': .02,
                    'retract_mm': 2.}
WAVEFRONT_LEFT_MM2 = .5  # reachable stock left on one level above which the result is marked incomplete
WAVEFRONT_SIMPLIFY = .01  # mm; largest deviation when thinning the dense planned points for output
