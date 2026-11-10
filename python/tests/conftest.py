"""Shared test fixtures and path helpers.

``FIXTURES`` points at the top-level ``fixtures/`` directory, which lives at the
monorepo root (two levels above this ``python/tests/conftest.py`` file). It is
resolved relative to this file so the tests work regardless of the current
working directory. The fixture set is shared across language implementations,
hence its placement outside ``python/``:

    fixtures/
      sources/braket/   # raw vendor payloads (importer inputs)
      sources/boulder-opal/
      sources/quam/
      oq-cal-docs/        # valid_*/invalid_* oq-cal documents
      conformance/      # cross-language test vectors
"""

from __future__ import annotations

from pathlib import Path

import pytest

# python/tests/conftest.py -> python/tests -> python -> repo root -> fixtures
FIXTURES = (Path(__file__).resolve().parents[2] / "fixtures").resolve()


def _json_files(subdir: str):
    return sorted((FIXTURES / subdir).glob("*.json"))


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES


def pytest_generate_tests(metafunc):
    """Parametrize tests over fixture files by requesting a *_file fixture name."""
    mapping = {
        "braket_file": "sources/braket",
        "boulder_opal_file": "sources/boulder-opal",
        "quam_file": "sources/quam",
        "oq_cal_valid_file": "oq-cal-docs",
        "oq_cal_invalid_file": "oq-cal-docs",
    }
    for argname, subdir in mapping.items():
        if argname in metafunc.fixturenames:
            files = _json_files(subdir)
            if argname == "oq_cal_valid_file":
                files = [f for f in files if f.name.startswith("valid_")]
            elif argname == "oq_cal_invalid_file":
                files = [f for f in files if f.name.startswith("invalid_")]
            metafunc.parametrize(argname, files, ids=[f.name for f in files])
