"""Shared validation for CAM lead-in angles, expressed in degrees."""
import math

from .cam_constants import LEAD_ANGLE_RANGE


def lead_slope(angle):
    """Return the maximum vertical drop per horizontal millimetre."""
    lo, hi = LEAD_ANGLE_RANGE
    if not lo <= angle <= hi:
        raise ValueError(f'Lead-in angle must be between {lo:g} and {hi:g} degrees')
    return math.tan(math.radians(angle))
