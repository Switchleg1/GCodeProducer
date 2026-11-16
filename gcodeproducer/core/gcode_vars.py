"""Compatibility exports. Implementation: gcodeproducer.core.gcode.variables."""
from gcodeproducer.core.gcode.template_variable import Var
from gcodeproducer.core.gcode.gcode_constants import (
    VARIABLES,
    _BY_NAME,
    DEFAULT_START,
    DEFAULT_END,
    TEMPLATE_FDM as FDM,
    TEMPLATE_CAM as CAM,
    TEMPLATE_BOTH as BOTH,
)
from gcodeproducer.core.gcode.variables import (
    variables_for,
    names_for,
    example_values,
    _num,
    job_variables,
    _file_name,
    render_box,
)
