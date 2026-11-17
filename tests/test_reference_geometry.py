"""Construction, stable references, compute picking and actual machining boundaries."""
import json
import numpy as np
import pytest

from gcodeproducer.core.cam import CAMSetup, Depth, Reference, Topology, generate, highlight_geometry, pick_geometry
from gcodeproducer.core.cam.reference_shape import ReferenceShape
from gcodeproducer.core.cam.reference_geometry import plane_point
from gcodeproducer.core.cam.cam_constants import REFERENCE_CHORD_ERROR
from gcodeproducer.stages.base import StageContext
from tests.test_pocket_bounds import stepped_part, job_for


@pytest.mark.parametrize("kind,method,first,second,center,size", [
    ("circle","center",(2,3),(5,7),(2,3),5),
    ("circle","edge",(-3,2),(7,2),(2,2),5),
    ("rectangle","center",(2,3),(-2,7),(2,3),(4,4)),
    ("rectangle","edge",(6,7),(-2,-1),(2,3),(4,4)),
])
def test_construction_methods(kind,method,first,second,center,size):
    shape=ReferenceShape(kind,method,first,second,z=-4)
    c,s=shape.dimensions()
    assert np.allclose(c,center) and np.allclose(s,size)
    p=shape.polyline()
    assert np.array_equal(p[0],p[-1]) and np.all(p[:,2]==-4)
    assert shape.contains(center) and not shape.contains((100,100))
    if kind=="circle":
        assert np.allclose(np.linalg.norm(p[:,:2]-center,axis=1),size)
        assert size*(1-np.cos(np.pi/shape.segment_count())) <= REFERENCE_CHORD_ERROR+1e-12
    else:
        assert len(p)==5
        assert np.allclose(p[:,:2].min(axis=0),np.asarray(center)-size)


@pytest.mark.parametrize("kwargs", [
    {"first":(0,0),"second":(0,0)},
    {"kind":"rectangle","first":(0,0),"second":(0,4)},
    {"z":float("nan")}, {"first":(float("inf"),0)},
    {"kind":"triangle"}, {"construction":"unknown"}, {"first":(1,2,3)}, {"id":""},
])
def test_invalid_reference_geometry_rejected(kwargs):
    with pytest.raises(ValueError):ReferenceShape(**kwargs)


def test_circle_segment_budget_is_a_failure_not_silent_coarsening():
    with pytest.raises(ValueError,match="too large"):
        ReferenceShape(first=(0,0),second=(1e10,0)).segment_count()


def test_plane_intersection_and_parallel_or_behind_camera():
    assert np.allclose(plane_point([2,3,10],[0,0,-1],-5),[2,3,-5])
    assert plane_point([0,0,10],[1,0,0],0) is None
    assert plane_point([0,0,10],[0,0,1],0) is None
    assert plane_point([0,0,10],[0,0,float('nan')],0) is None


def test_setup_round_trip_ids_and_depth_links_are_stable():
    first=ReferenceShape();second=ReferenceShape(kind="rectangle",z=-3)
    setup=CAMSetup(reference_shapes=[first,second])
    from gcodeproducer.core.cam import Operation, ToolGroup
    op=Operation(geometry=[Reference("drawing",[first.id])],end=Depth("geometry",reference=Reference("drawing",[second.id])))
    setup.groups=[ToolGroup("tool",[op])]
    restored=CAMSetup.from_dict(json.loads(json.dumps(setup.to_dict())))
    assert restored.to_dict()==setup.to_dict()
    restored.reference_shapes.pop(0)
    topo=Topology(stepped_part(),restored.reference_shapes)
    assert np.all(topo.points(op.end.reference)[:,2]==-3)
    with pytest.raises(ValueError,match="deleted"):
        topo.points(op.geometry[0])
    legacy=setup.to_dict();del legacy['reference_shapes']
    assert CAMSetup.from_dict(legacy).reference_shapes==[]
    duplicate=setup.to_dict();duplicate['reference_shapes'][1]['id']=first.id
    with pytest.raises(ValueError,match="unique"):CAMSetup.from_dict(duplicate)


@pytest.mark.parametrize("mode,mouse",[("reference_edge",(150,100)),("reference_face",(100,100)),("mixed_edge",(150,100))])
def test_drawing_outline_and_interior_are_pickable(mode,mouse):
    shape=ReferenceShape(first=(0,0),second=(5,0),z=-2)
    mesh=stepped_part();mvp=np.diag([.1,.1,.01,1.])
    result=pick_geometry((mesh,mode,[5 if mode.endswith('edge') else 0,0,100],[0,0,-1],mvp,[200,200],mouse,None,[shape]))
    assert result['reference']==Reference('drawing',[shape.id])
    assert result['z_min']==result['z_max']==-2


def test_drawing_highlights_include_unselected_outlines_and_selected_edges():
    mesh=stepped_part();a=ReferenceShape();b=ReferenceShape(kind="rectangle",z=-4)
    from gcodeproducer.core.cam import Operation
    ref=Reference("drawing",[b.id]);op=Operation(geometry=[ref],end=Depth("geometry",reference=ref))
    output=highlight_geometry((mesh,op,None,None,[],[a,b],a.id))
    assert len(output['reference_geometry'])==2*a.segment_count()+8
    assert len(output['reference_edges'])==8
    assert len(output['reference_selection_fill']) == 12
    assert len(output['reference_focus_fill']) == 3*a.segment_count()
    assert np.all(output['reference_selection_fill'][:, 2] == -4)
    from gcodeproducer.gui.rendering.rendering_constants import REFERENCE_COLOR, REFERENCE_FOCUS_COLOR, REFERENCE_SELECTION_FILL
    assert np.linalg.norm(np.array(REFERENCE_COLOR[:3])-REFERENCE_FOCUS_COLOR[:3]) > .5
    assert REFERENCE_SELECTION_FILL[3] >= .25
    assert 'end -4.000' in output['depths']
    assert not output['faces'] and not len(output['stock_edges'])


@pytest.mark.parametrize("shape_kind,method",[("circle","center"),("circle","edge"),("rectangle","center"),("rectangle","edge")])
@pytest.mark.parametrize("operation_kind",["pocket","profile","slot","engrave","drill"])
def test_drawn_boundaries_generate_real_operations(libset,shape_kind,method,operation_kind):
    shape=ReferenceShape(shape_kind,method,(-6,-4),(6,4),z=-2)
    job,op=job_for(stepped_part(),[Reference("drawing",[shape.id])],libset)
    job.cam_setup.reference_shapes=[shape]
    op.kind=operation_kind
    if operation_kind == "drill" and shape_kind == "rectangle":
        with pytest.raises(ValueError,match="circular"):
            generate(job,StageContext())
        return
    generate(job,StageContext())
    assert job.layers and any(layer.paths for layer in job.layers)
    assert min(layer.z for layer in job.layers)==-2


def test_material_envelope_can_retain_a_drawn_inner_boundary(libset):
    from shapely.geometry import Polygon, Point
    shape=ReferenceShape("rectangle","center",(0,0),(20,20),z=-4)
    job,op=job_for(stepped_part(),[Reference("stock_face",[1]),Reference("drawing",[shape.id])],libset)
    job.cam_setup.reference_shapes=[shape]
    job.cam_setup.stock.margin=5
    job.cam_setup.stock.auto(job.mesh)
    generate(job,StageContext())
    retained=Polygon(shape.polyline()[:,:2])
    assert job.layers and any(layer.paths for layer in job.layers)
    for layer in job.layers:
        for path in layer.paths:
            assert all(retained.distance(Point(p)) >= 1.45 for p in path.points)


def test_reference_pocket_emits_a_complete_program(libset):
    from gcodeproducer.stages.cam_emit import CAMEmit
    shape=ReferenceShape("circle","center",(0,0),(6,0),z=-2)
    job,op=job_for(stepped_part(),[Reference("drawing",[shape.id])],libset)
    job.cam_setup.reference_shapes=[shape]
    generate(job,StageContext())
    CAMEmit().run(job,CAMEmit.defaults(),StageContext())
    assert job.program is not None and any(line.cmd=="G1" for line in job.program.lines)


def test_deleted_drawing_reference_fails_generation(libset):
    job,op=job_for(stepped_part(),[Reference("drawing",["missing"])],libset)
    op.end=Depth("absolute",-2)
    with pytest.raises(ValueError,match="deleted"):
        generate(job,StageContext())
