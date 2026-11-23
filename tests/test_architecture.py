import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "architecture", Path(__file__).resolve().parents[1] / "scripts/check_architecture.py"
)
architecture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(architecture)


@pytest.mark.parametrize(
    "source",
    [
        "import requests",
        "from pathlib import Path",
        "import socket",
        "from eval_orchestrator.adapters.fixture import FixtureAdapter",
        "from eval_orchestrator import adapters",
        "from ..adapters import fixture",
        "__import__('socket')",
        "importlib.import_module('socket')",
    ],
)
def test_boundary_guard_catches_known_bad_dependencies(source):
    assert architecture.violations(source, "domain")


def test_boundary_guard_allows_pure_domain_dependencies():
    assert not architecture.violations("from dataclasses import dataclass", "domain")


def test_application_cannot_construct_its_own_adapter():
    assert architecture.violations("import eval_orchestrator.adapters.fixture", "application")
