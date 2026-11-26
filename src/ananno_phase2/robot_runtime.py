"""Project-local optional robot dependencies; no global Python changes."""
import os
from pathlib import Path
import sys


def prepare_robot_runtime(project_dir, *, preload=False):
    directory=Path(os.environ.get('ANANNO_ROBOT_DEPS') or Path(project_dir)/'robot_runtime/site-packages')
    if directory.is_dir() and str(directory) not in sys.path:sys.path.insert(0,str(directory))
    if preload:
        # Windows bundled plugins must be loaded before Qt creates its application.
        import mujoco
    return directory
