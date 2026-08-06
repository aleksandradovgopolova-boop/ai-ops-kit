"""Setup for ai-ops-kit with flat module layout.

The tools/ and validation/ directories contain modules that should be
importable as top-level names (e.g. `import orchestrator`).
This setup installs a .pth file that adds those directories to sys.path.
"""
import os
import site
from pathlib import Path
from setuptools import setup

SETUP_DIR = Path(__file__).resolve().parent


def _write_pth():
    """Write a .pth file into site-packages so tools/ and validation/ are on sys.path."""
    site_dir = site.getusersitepackages()
    os.makedirs(site_dir, exist_ok=True)
    pth_path = os.path.join(site_dir, "ai_ops_kit.pth")
    # .pth files execute each line starting with 'import' as a single statement.
    # Adds: project root (for `import tools.x`), tools/ and validation/ (for `import x`).
    line = (
        "import os, sys; "
        "[sys.path.insert(0, p) for p in "
        "[{root!r}] + [os.path.join({root!r}, d) for d in ('tools', 'validation')] "
        "if os.path.isdir(p) and p not in sys.path]"
    ).format(root=str(SETUP_DIR))
    with open(pth_path, "w") as f:
        f.write(line + "\n")


# Write .pth file when setup.py is executed (pip install -e .)
_write_pth()

setup()
