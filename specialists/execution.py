"""Accidental-local-execution guards. These are not provider attestation."""
import os
from pathlib import Path
import sys


def require_remote(project_root, data_directory, output_directory, *, child=False):
    base = Path('/workspace')
    paths = [Path(p).resolve() for p in (project_root, data_directory, output_directory)]
    if (sys.platform != 'linux' or not os.environ.get('RUNPOD_POD_ID')
            or not os.path.ismount(base) or any(not p.is_relative_to(base) or p == base for p in paths)):
        raise ValueError('Execute only on the remote Pod with its Pod ID and project/data/output under mounted /workspace')
    if child and os.environ.get('POLICYPILOT_SPECIALIST_CHILD') != '1':
        raise ValueError('Use the bounded specialists.run launcher for model execution')
    if not paths[1].is_relative_to(paths[0]):
        raise ValueError('Training data must belong to the verified remote project')
    if paths[2].is_relative_to(paths[0]):
        raise ValueError('Write run outputs outside the frozen source project')
    return paths
