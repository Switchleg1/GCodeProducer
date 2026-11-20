"""Frozen planar inputs for offline adaptive corner and slot trials (mm)."""
from shapely.geometry import box


def corner_slot_fixtures():
    """Return (pocket, initial stock, incoming XY, heading) for each fixture."""
    corners = {
        'sharp_corner': box(0, 0, 24, 14),
        'round_corner': box(4, 4, 20, 10).buffer(4, quad_segs=64),
    }
    fixtures = {
        name: (pocket, pocket.difference(pocket.buffer(-.5, quad_segs=64))
                      .intersection(box(8, -1, 25, 10)), (6., 1.25), (1., 0.))
        for name, pocket in corners.items()
    }
    for name, width in [('wide_slot', 6.), ('narrow_slot', 2.4)]:
        pocket = box(0, 0, 32, width)
        fixtures[name] = pocket, box(5, 0, 32, width), (4., width / 2), (1., 0.)
    return fixtures
