"""CAM rectangular stock and conservative, cutter-radius-aware motion checks.

This is NOT a stock-removal or holder/fixture simulation. Rapids are checked
against the original blank, even where an earlier operation may have cleared
it. Custom arcs and controller-specific motion are explicitly unverifiable.
"""


from dataclasses import asdict, dataclass
import math, re, numpy as np


@dataclass
class Stock:
    category: str = "soft_wood"  # machining material, independent of FDM filament
    material: str = "Unspecified"
    density: float = 0.0  # g/cm³; descriptive, not a feed/speed calculator
    margin: float = 2.0  # per XY side and beneath the part; surface stays at Z0
    x: float = 0.0      # minimum X/Y, top Z
    y: float = 0.0
    top: float = 0.0
    width: float = 0.0
    depth: float = 0.0
    height: float = 0.0

    @property
    def allocated(self):
        return all(math.isfinite(v) and v > 0 for v in (self.width, self.depth, self.height))

    @property
    def bounds(self):
        return (np.array([self.x, self.y, self.top - self.height]),
                np.array([self.x + self.width, self.y + self.depth, self.top]))

    def auto(self, mesh):
        lo, hi = mesh.bounds
        m = max(0.0, self.margin)
        self.x, self.y = float(lo[0] - m), float(lo[1] - m)
        self.width, self.depth = float(hi[0] - lo[0] + 2*m), float(hi[1] - lo[1] + 2*m)
        self.top = max(0.0, float(hi[2]))
        self.height = max(0.001, float(self.top - lo[2] + m))

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


def _intersects(a, b, lo, hi):
    """Segment / AABB slab test (strict interior, not tangent contact)."""
    t0, t1 = 0.0, 1.0
    for i in range(3):
        delta = b[i] - a[i]
        if abs(delta) < 1e-12:
            if a[i] <= lo[i] or a[i] >= hi[i]:
                return False
        else:
            u, v = sorted(((lo[i] - a[i]) / delta, (hi[i] - a[i]) / delta))
            t0, t1 = max(t0, u), min(t1, v)
            if t0 >= t1:
                return False
    return t0 < t1


def check_stock(job, program, sim=None, progressive=False):
    """Warnings, with G-code line numbers. Intended cuts/plunges are not rapid collisions."""
    from gcodeproducer.core.gcode.simulation import simulate
    from gcodeproducer.core.gcode.gcode_constants import CAM_CUT_FEATURES
    stock = getattr(job.cam_setup, "stock", None)
    if stock is None or not stock.allocated:
        return ["CAM stock is not allocated; material collision checking could not run."]
    warnings = []
    def warn(message):
        if len(warnings) < 100:
            warnings.append(message)
    lo, hi = stock.bounds
    if job.mesh is not None:
        ml, mh = job.mesh.bounds
        if np.any(ml < lo - 1e-3) or np.any(mh > hi + 1e-3):
            warn("The part is not fully contained in the allocated material; resize the stock or use Auto.")
    if float(job.m("safe_z", 15)) <= stock.top + 1e-4:
        warn("Safe Z is at or below the material surface; rapid moves may strike the stock.")
    tools = {int(t.get("tool_number", 1)): t for t in job.tools}
    radius = max((float(t.get("diameter", 0))/2 for t in job.tools), default=0)
    sim = sim or simulate(program)
    spindle = False
    entry_depth = {}  # exact same-XY/radius plunge history; not a cleared-volume model
    for i, ln in enumerate(program.lines):
        cmd = ln.cmd
        if cmd in ("M3", "M4"):
            spindle = ln.params.get("S", 1) > 0
        elif cmd == "M5":
            spindle = False
        tool = tools.get(int(sim.tool[i]))
        r = float(tool.get("diameter", 0))/2 if tool else radius
        a = np.array([sim.px[i], sim.py[i], sim.pz[i]])
        b = np.array([sim.x[i], sim.y[i], sim.z[i]])
        # A cylindrical cutter extends above its tip. Conservative square XY envelope.
        blo = np.array([lo[0] - r + 1e-5, lo[1] - r + 1e-5, -1e12])
        bhi = np.array([hi[0] + r - 1e-5, hi[1] + r - 1e-5, hi[2] - 1e-5])
        contact = _intersects(a, b, blo, bhi)
        label = f"Line {i+1}"
        if cmd and cmd.startswith("G") and cmd not in (
                "G0", "G1", "G2", "G3", "G4", "G17", "G18", "G19", "G20", "G21", "G90", "G91", "G94"):
            warn(f"{label}: {cmd} is not modelled for stock checking; controller offsets, compensation or cycles may change clearance.")
        if cmd in ("G2", "G3"):
            warn(f"{label}: custom arc motion is not stock-checked; verify in a machine-aware simulator.")
        code = re.sub(r"\([^)]*\)", "", ln.raw.split(";", 1)[0]).upper()
        commands = re.findall(r"[GMT]\d+(?:\.\d+)?", code)
        if sum(c.startswith("G") for c in commands) > 1:
            warn(f"{label}: multiple G commands in a custom block cannot be fully stock-checked.")
        if "M6" in commands and b[2] <= stock.top:
            warn(f"{label}: tool change at/below the material surface.")
        if progressive:
            continue  # current-material simulator checks motion/contact and removes stock in order
        if not sim.motion[i] or not sim.moved[i]:
            continue
        if min(a[2], b[2]) < lo[2] - 1e-4:
            warn(f"{label}: motion below the material bottom; risk of hitting the table/spoilboard.")
        upward_retract = np.linalg.norm(b[:2] - a[:2]) < 1e-6 and b[2] > a[2]
        if sim.motion_cmd[i] == "G0" and contact and not upward_retract:
            warn(f"{label}: rapid motion intersects the original material (tool radius {r:g} mm).")
        elif sim.motion_cmd[i] == "G1" and contact and not upward_retract:
            intended = (ln.feature in CAM_CUT_FEATURES or ln.feature in ("plunge", "lead_in", "lead_out")) and ln.op is not None
            if not intended:
                warn(f"{label}: custom/unclassified feed move enters the material.")
            if not spindle:
                warn(f"{label}: feed move contacts material with the spindle stopped.")
            if intended and np.linalg.norm(b[:2] - a[:2]) < 1e-6 and b[2] < a[2]:
                key = (round(float(b[0]), 4), round(float(b[1]), 4), round(r, 4))
                previous = min(stock.top, entry_depth.get(key, stock.top), float(a[2]))
                doc = float(tool.get("max_doc", 0) or 0) if tool else 0
                if doc > 0 and previous - b[2] > doc + 1e-3:
                    warn(f"{label}: estimated uncleared entry depth {previous-b[2]:g} mm exceeds tool depth per pass {doc:g} mm; verify prior clearing.")
                entry_depth[key] = min(previous, float(b[2]))

    return warnings
