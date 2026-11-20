"""SVG diagnostic plot for an ordered planar replay."""
from gcodeproducer.core.geometry.polygon_parts import polygons


def write_overlay(out, pocket, residual, strokes):
    """Plot (source line, XY points, already swept) strokes in work coordinates."""
    strokes = list(strokes)
    x0, y0, x1, y1 = pocket.bounds
    for _, points, _ in strokes:
        xs, ys = zip(*points)
        x0, y0 = min(x0, min(xs)), min(y0, min(ys))
        x1, y1 = max(x1, max(xs)), max(y1, max(ys))
    unit = max(x1-x0, y1-y0) / 100

    def xy(point):
        return f'{point[0]:.6f},{-point[1]:.6f}'

    print(f'<svg xmlns="http://www.w3.org/2000/svg" width="1100" '
          f'viewBox="{x0-4*unit} {-y1-8*unit} {x1-x0+8*unit} {y1-y0+12*unit}">', file=out)
    print(f'<text x="{x0}" y="{-y1-4*unit}" font-size="{1.8*unit}">'
          'Blue: new sweep | Gray: prior sweep | Orange: reachable residual | Labels: G-code line</text>', file=out)
    for shape, role, color in ((pocket, 'pocket', '#f2f4f6'), (residual, 'residual', '#fa801a')):
        for part in polygons(shape):
            path = ' '.join('M ' + ' '.join(map(xy, ring.coords)) + ' Z'
                            for ring in (part.exterior, *part.interiors))
            print(f'<path data-role="{role}" d="{path}" fill="{color}" fill-rule="evenodd"/>', file=out)
    for line, points, clear in strokes:
        color = '#83909f' if clear else '#1766ac'
        print(f'<polyline data-line="{line}" data-role="{"prior" if clear else "new"}" '
              f'points="{" ".join(map(xy, points))}" fill="none" stroke="{color}" '
              f'stroke-width="{.14*unit}"><title>G-code line {line}</title></polyline>', file=out)
    stride = max(1, (len(strokes)+23)//24)
    for index, (line, points, _) in enumerate(strokes):
        if index % stride and index != len(strokes)-1:
            continue
        x, y = points[0]
        print(f'<text x="{x}" y="{-y}" fill="#182330" font-size="{1.15*unit}">{line}</text>', file=out)
    print('</svg>', file=out)
