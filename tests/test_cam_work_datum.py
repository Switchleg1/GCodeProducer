from copy import deepcopy
import numpy as np
import pytest
from gcodeproducer.core.cam.depth import Depth
from gcodeproducer.core.cam.reference_shape import ReferenceShape
from gcodeproducer.core.jobs.session import slice_job
from gcodeproducer.core.gcode.simulation import simulate
from tests.test_pocket_bounds import floor_ref, job_for, stepped_part


@pytest.mark.parametrize('side',['a','b'])
def test_bed_datum_translates_nc_not_the_saved_setup(libset,side):
    mesh=stepped_part(); original,op=job_for(mesh,[floor_ref(mesh)],libset)
    setup=original.cam_setup
    setup.set_two_sided(True)
    setup.other_groups=deepcopy(setup.groups)
    setup.switch_side(side)
    setup.groups[0].operations[0].end=Depth('absolute',-2.)
    setup.reference_shapes.append(ReferenceShape(z=-1.))
    bed=deepcopy(original); saved=bed.cam_setup; baseline=saved.to_dict()
    bed.machine.values['cam_z0_at_bed']=True
    slice_job(original); slice_job(bed)
    dz=setup.stock.height-setup.stock.top
    assert saved.to_dict()==baseline
    assert bed.cam_setup.stock.bounds[0][2]==0
    assert bed.cam_setup.reference_shapes[0].z==dz-1
    assert bed.cam_setup.groups[0].operations[0].end.value==dz-2
    assert np.allclose(bed.mesh.vertices,original.mesh.vertices+[0,0,dz])
    assert np.allclose([l.z for l in bed.layers],np.array([l.z for l in original.layers])+dz)
    p,q=simulate(original.program),simulate(bed.program)
    for sim,program in ((p,original.program),(q,bed.program)):
        assert len(program.lines)==len(sim.z)
    cut=lambda sim,prog: np.array([(x,y,z) for x,y,z,l in zip(sim.x,sim.y,sim.z,prog.lines)
                                   if l.cmd=='G1' and l.feature in ('hsm','cut','slot','high_engagement','conflict')])
    assert np.allclose(cut(q,bed.program),cut(p,original.program)+[0,0,dz],atol=.001001)
    rapids=q.z[np.array(q.motion_cmd)=='G0']
    assert rapids.min()==pytest.approx(setup.stock.height+bed.m('clearance_z',5))
    assert rapids.max()==pytest.approx(setup.stock.height+bed.m('safe_z',15))


def test_bed_datum_requires_stock_and_room_to_retract(libset):
    mesh=stepped_part(); job,_=job_for(mesh,[floor_ref(mesh)],libset)
    job.machine.values.update(cam_z0_at_bed=True,work_z=10)
    with pytest.raises(ValueError,match='Safe Z exceeds'): slice_job(deepcopy(job))
    job.cam_setup.stock.height=0
    with pytest.raises(ValueError,match='allocated stock'): slice_job(job)
