"""Persistent 2.5D material state: exact planar sweeps for planning, a height
field for progress display and motion checks. Neither models fixtures/holders.
"""

from gcodeproducer.core.cam.planar_stock import PlanarStock
from gcodeproducer.core.cam.height_stock import HeightStock
from gcodeproducer.core.cam.cam_constants import RAMP_ANGLE, RAMP_TAN
import numpy as np


def height_stock_for(job,stock):
    from gcodeproducer.core.settings.preferences import pref
    state=HeightStock(stock,pref(job,"stock_resolution"),pref(job,"stock_max_cells"))
    if job.cam_setup is not None and job.cam_setup.tabs:
        from gcodeproducer.core.cam.tabs import resolve_tabs
        state.tabs=resolve_tabs(job.mesh,job.cam_setup)
    return state


def simulate_material(job,program,log=None,*,sim=None):
    """Execute emitted moves in order, preserving material across all operations."""
    from gcodeproducer.core.gcode.simulation import simulate
    stock=getattr(job.cam_setup,"stock",None)
    if stock is None or not stock.allocated:return [],[]
    state=height_stock_for(job,stock)
    if sim is None:sim=simulate(program)
    by_id={t.id:t.resolved() for t in job.tools}
    tools={int(by_id[t.id].get("tool_number",1)):by_id[t.id] for t in job.tools}
    layer_tools={layer.index:by_id.get(getattr(layer,"cam_tool_id",None)) for layer in job.layers}
    fallback=by_id[job.tools[0].id] if job.tools else None
    snapshots=[{"label":"Initial material","last_layer":-1,"positions":state.surface(),
                "resolution":state.resolution,"heights":state.heights.copy()}]
    warnings=[];spindle=False;last_op=None;last_layer=-1
    from gcodeproducer.core.gcode.gcode_constants import CAM_CUT_FEATURES
    intended=CAM_CUT_FEATURES|{"plunge","lead_in","lead_out"}
    def warn(text):
        if len(warnings)<100 and text not in warnings:warnings.append(text)
    if state.coarsened:
        warn(f"Material grid coarsened from {state.requested:g} to {state.resolution:g} mm by the global cell limit; raise it in Settings for finer checks.")
    def snapshot(label):
        snapshots.append({"label":label,"last_layer":last_layer,"positions":state.surface(),
                          "resolution":state.resolution,"heights":state.heights.copy()})
    for i,line in enumerate(program.lines):
        if line.op and line.op!=last_op:
            if last_op is not None:snapshot(last_op)
            last_op=line.op
        if line.op:last_layer=max(last_layer,line.layer)
        if line.cmd in ("M3","M4"):spindle=line.params.get("S",1)>0
        elif line.cmd=="M5":spindle=False
        if not sim.motion[i] or not sim.moved[i]:continue
        tool=(layer_tools.get(line.layer) if line.op else None) or tools.get(int(sim.tool[i]),fallback)
        if tool is None:continue
        radius=float(tool.get("diameter",0))/2
        if 2*radius<2*state.resolution:
            warn("Tool diameter is below twice the material grid resolution; small contacts/removal may be missed. Use a finer grid.")
        a=np.array([sim.px[i],sim.py[i],sim.pz[i]])
        b=np.array([sim.x[i],sim.y[i],sim.z[i]])
        contact=state.contact(a,b,radius)
        up=np.linalg.norm(a[:2]-b[:2])<1e-6 and b[2]>a[2]
        label=f"Line {i+1}"
        if not up and state.tab_contact(a,b,radius):
            warn(f"{label}: cutter motion intersects a protected holding tab.")
        if min(a[2],b[2])<state.bottom-1e-3:warn(f"{label}: motion below material bottom; table/spoilboard risk.")
        if sim.motion_cmd[i]=="G0" and contact and not up:
            warn(f"{label}: rapid motion contacts CURRENT remaining material (grid {state.resolution:g} mm).")
        elif sim.motion_cmd[i] in ("G1","G2","G3") and contact and not up:
            if line.feature not in intended or not line.op:
                warn(f"{label}: unclassified feed contacts current material.")
            if not spindle:warn(f"{label}: material contact with spindle stopped.")
        if contact and line.feature in ("plunge","lead_in") and b[2]<a[2]:
            horizontal=float(np.linalg.norm(b[:2]-a[:2]))
            drop=float(a[2]-b[2])
            if horizontal>1e-6 and drop<=horizontal*RAMP_TAN+1e-6:
                pass  # ramped entry within the ramp angle: the tool tip descends gradually; walls beside it are side cutting
            else:
                # Plunge (or over-steep ramp): material under the tool that this move itself descends
                # through. Material above the move's start height is side contact, not axial entry.
                doc=float(tool.get("max_doc",0) or 0)
                uncleared=min(state.height_at(b[:2],radius),float(a[2]))-b[2]
                if doc>0 and uncleared>doc+state.resolution:
                    kind="plunge" if horizontal<=1e-6 else f"ramp steeper than {RAMP_ANGLE:g}°"
                    warn(f"{label}: estimated uncleared entry depth {uncleared:g} mm ({kind}) exceeds tool depth/pass {doc:g}; verify prior clearing.")
        if sim.motion_cmd[i]=="G1" and spindle and line.feature in intended and line.op:
            state.cut(a,b,radius)
    if last_op is not None:snapshot(last_op)
    if log:log(f"  current material: {state.nx} x {state.ny} cells, {state.resolution:g} mm, {len(snapshots)-1} operation outputs")
    return warnings,snapshots
