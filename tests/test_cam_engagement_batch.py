"""Batched chord predicates must keep the left and right stock clips separate."""
import numpy as np
from shapely import linestrings
from shapely.geometry import box

from gcodeproducer.core.cam.engagement import _occupied


def test_chord_batch_handles_covered_crossing_and_empty_sides():
    stock = box(0, 0, 5, 5).difference(box(2, 1, 3, 4))
    chords = linestrings([[[[0, 0], [2, 0]], [[1, 2], [4, 2]], [[6, 1], [8, 1]]],
                          [[[6, 6], [8, 6]], [[8, 6], [10, 6]], [[10, 6], [12, 6]]]])
    np.testing.assert_array_equal(_occupied(chords, stock), [[2., 2., 0.], [0., 0., 0.]])
