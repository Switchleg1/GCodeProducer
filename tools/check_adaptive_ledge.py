"""Offline XYZ proposal/replay on a synthetic ledge. No production toolpath or export."""
import numpy as np


def trial(pitch=.05):
    # Blank top Z0; a 4 mm flat cutter. The preceding pass goes east at Y0,
    # rises from Z-2 to -1, then levels out. Only inspect the interior crossing;
    # entry and return to the start are NOT modeled.
    x, y = np.meshgrid(np.arange(0, 24, pitch) + pitch/2,
                       np.arange(-5, 5, pitch) + pitch/2)
    def ramp(t):
        return -2 + np.clip((t-8)/6, 0, 1)

    prior = abs(y) <= 2
    # Earliest disk contact gives the lowest tip on a monotone ascending pass.
    before = np.where(prior, ramp(x-np.sqrt(np.maximum(0, 4-y*y))), 0.)

    def replay(lines):
        stock = before.copy()
        bottom = width = gain = 0.
        for i, line in enumerate(lines):
            b = np.array([float(w[1:]) for w in line.split()[1:]])
            if i:
                assert b[0] > a[0] and b[1] == a[1] and b[2] >= a[2]
                half = np.sqrt(np.maximum(0, 4-(y-b[1])**2))
                hit = (abs(y-b[1]) <= 2) & (x+half >= a[0]) & (x-half <= b[0])
                t = np.clip((x-half-a[0])/(b[0]-a[0]), 0, 1)
                z = a[2]+t*(b[2]-a[2])
                dz = np.where(hit, np.maximum(stock-z, 0), 0)
                bottom = max(bottom, dz[prior].max())
                rows = np.flatnonzero((dz > 1e-8).any(axis=1))
                if rows.size:
                    width = max(width, (rows[-1]-rows[0]+1)*pitch)
                gain += dz.sum()*pitch*pitch
                stock -= dz
            a = b
        return dict(bite_mm=round(float(bottom),6), width_mm=round(float(width),6), removed_mm3=round(float(gain),4))

    reports = {}
    for name, advance in [('flat', None), ('copied_ramp', 0), ('early_0.5', .5), ('early_1', 1), ('early_1.5', 1.5)]:
        lines = [f'G1 X{t:.3f} Y0.300 Z{(-2 if advance is None else ramp(t+advance)):.3f}' for t in range(-3,28)]
        result = reports[name] = replay(lines)
        # At the old strip edge (Y2), the old disk just touched, but the new
        # disk reaches sqrt(R²-(R-step)²) farther forward. This is the largest
        # extra reach on the shared strip. A cell-centre grid can miss it.
        edge_lead = np.sqrt(4 - (2-.3)**2)
        if (advance is not None and advance >= edge_lead + .003
                and result['bite_mm'] <= .001 and result['width_mm'] <= .4 and result['removed_mm3'] > 0):
            return name, reports
    return None, reports


if __name__ == '__main__':
    for spacing in (.1, .05, .025):
        print(spacing, trial(spacing))
