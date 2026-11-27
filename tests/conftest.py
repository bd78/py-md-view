"""Load md-view.py as a module: the hyphen in its name rules out a plain import."""

import importlib.util
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(scope="session")
def mdv():
    spec = importlib.util.spec_from_file_location("mdview", ROOT / "md-view.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
