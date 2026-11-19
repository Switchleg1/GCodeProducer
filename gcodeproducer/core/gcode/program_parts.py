"""File names for programs split into separate files (one per tool)."""
import re
from pathlib import Path


def part_path(path, index, label):
    """``part.nc`` -> ``part_01_T1-6mm-flat-endmill.nc``: sortable in tool order."""
    path = Path(path)
    safe = re.sub(r'[^\w.-]+', '-', label).strip('-') or 'tool'
    return str(path.with_name(f'{path.stem}_{index:02d}_{safe}{path.suffix}'))
