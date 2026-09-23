import importlib.util
import sys
from pathlib import Path

import pytest

from qdojo.combat.rules import candidate_1

ROOT = Path(__file__).resolve().parents[4]


@pytest.fixture(scope="session")
def rules():
    return candidate_1()


@pytest.fixture(scope="session")
def reference():
    """docs/reference/combat_v1.py: an independent oracle, never imported by the engine."""
    spec = importlib.util.spec_from_file_location("combat_v1_reference", ROOT / "docs/reference/combat_v1.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod   # dataclasses resolve their module through sys.modules
    spec.loader.exec_module(mod)
    return mod
