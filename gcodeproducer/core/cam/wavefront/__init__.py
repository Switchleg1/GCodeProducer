"""Wavefront pocket clearing: helical starts, outward spirals, then offset fronts at a steady peel.

Every pass is the cleared cutter-centre region grown by one stepover and clipped to the pocket;
each cut is replayed against the live stock and refused over the contact limit. See
docs/cam/wavefront-clearing.md.
"""
from .stroke import Stroke
from .regions import spiral_pitch, clear_of, center_regions, find_lobes, choose_seeds, spiral_out, clearance, grow_clearance, fronts, eased, without_slivers, sweep, round_a_boss, channel_stretches
from .contact import cutting_pieces, chunk_contact, cut
from .walls import along_wall, walk_wall, fillet, turn_away, hook_to_wall, glance_onto_wall, bow_across, wall_ends, convex_corners, corner_pecks
from .links import stay_down_link, smooth_link, heading
from .timing import motion_time, machine_time
from .planner import clear_pocket, clear_depths
from .program import write_program
from .app_paths import plan_level, plan_levels, wavefront_paths
from .wavefront_constants import *  # noqa: F401,F403
