"""Every public entry point imports cleanly in a fresh interpreter (no circular imports)."""
import subprocess
import sys
import pytest

ENTRY_POINTS = [
    "gcodeproducer.core.libraries.library_set",
    "gcodeproducer.core.jobs.session",
    "gcodeproducer.core.cam",
    "gcodeproducer.core.cam.planning",
    "gcodeproducer.core.cam.planner",
    "gcodeproducer.core.cam.planner.motion_planner",
    "gcodeproducer.core.cam.operations",
    "gcodeproducer.stages.cam.cam_emit",
    "gcodeproducer.core.runtime.compute",
    "gcodeproducer.cli",
]


@pytest.mark.parametrize("module", ENTRY_POINTS)
def test_module_imports_first(module):
    result = subprocess.run([sys.executable, "-c", f"import {module}"],
                            stdin=subprocess.DEVNULL, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
