"""Compatibility exports. Implementation: gcodeproducer.core.fdm.support."""
from gcodeproducer.core.fdm.fdm_constants import SUPPORT_MODES
from gcodeproducer.core.fdm.model_support import ModelSupport
from gcodeproducer.core.fdm.support_block import SupportBlock
from gcodeproducer.core.fdm.support import (
    make_grid,
    support_polys,
    model_masks,
    margin_cells,
    overhangs,
    _gap_free,
    _with_margin,
    _bottom_gap,
    auto_columns,
    block_cells,
    block_columns,
    block_at,
    _components,
    blocks_from_columns,
    tiled_blocks_from_columns,
    slice_layers,
    generate_blocks,
)
