"""Write a before/after vector section through the 0.04 mm ridge fixture."""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from shapely.geometry import box
from gcodeproducer.core.cam.sweep_stock import SweepStock


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('output', type=Path)
    args = p.parse_args()
    stock = SweepStock((-6,-5,6,5), -4, 0, 1)
    for y in (-2.02, 2.02):
        stock.cut((-4,y,-2),(4,y,-2),2)
    panels = []
    for i, label in enumerate(('After two parallel cuts', 'After a centre plunge')):
        section = stock.remaining(-2,.001,box(-3,-1,3,1))
        panels.append(f'<text x="20" y="{25+140*i}">{label} at Z−2; remaining stock in green</text>'
                      f'<g transform="translate(200,{85+140*i}) scale(60,-60)">{section.svg(scale_factor=.001)}</g>')
        stock.cut((0,0,0),(0,0,-3),1)
    args.output.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="420" height="270">'+''.join(panels)+'</svg>',encoding='utf8')


if __name__ == '__main__':
    main()
