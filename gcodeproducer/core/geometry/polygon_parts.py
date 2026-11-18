"""Polygon members of Shapely results, excluding empty and non-area parts."""


def polygons(shape):
    if shape.geom_type == 'Polygon':
        if not shape.is_empty:
            yield shape
    elif hasattr(shape, 'geoms'):
        for child in shape.geoms:
            yield from polygons(child)
