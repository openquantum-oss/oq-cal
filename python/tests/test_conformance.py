"""Conformance suite: the Python importers must reproduce the pinned vectors.

Each vector under ``fixtures/conformance/<NN-name>/`` has a ``manifest.json``
(source payload, importer name, kwargs, description) and an ``expected.oq-cal.json``
produced by running that importer through the canonical JSON writer
(``oq_cal.io.to_canonical_json``). For every manifest we re-run the importer and
assert the result equals the expected document *structurally* (``json.loads`` on
both sides), so the test checks data agreement rather than byte formatting — the
latter is already pinned by the canonical writer's own tests.

Vectors are regenerable via ``python/scripts/generate_conformance.py``; a
behaviour change to any converter requires regenerating them and reviewing the
diff (see CONTRIBUTING.md).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from oq_cal import registry
from oq_cal.io import to_canonical_json

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"
CONFORMANCE = FIXTURES / "conformance"


def _vector_dirs() -> list[Path]:
    return sorted(p for p in CONFORMANCE.iterdir() if p.is_dir())


VECTOR_DIRS = _vector_dirs()


def test_vectors_present():
    """Guard against an empty/missing conformance vector set silently passing."""
    assert len(VECTOR_DIRS) == 14, VECTOR_DIRS


@pytest.mark.parametrize("vec_dir", VECTOR_DIRS, ids=[p.name for p in VECTOR_DIRS])
def test_conformance_vector(vec_dir: Path):
    manifest = json.loads((vec_dir / "manifest.json").read_text(encoding="utf-8"))
    expected = json.loads((vec_dir / "expected.oq-cal.json").read_text(encoding="utf-8"))

    source = FIXTURES / manifest["source"]
    assert source.exists(), f"{vec_dir.name}: source missing: {manifest['source']}"
    payload = json.loads(source.read_text(encoding="utf-8"))

    importer = registry.get_importer(manifest["importer"])
    result = importer(payload, **manifest.get("kwargs", {}))

    produced = json.loads(to_canonical_json(result))
    assert produced == expected, f"{vec_dir.name}: importer output drifted from pinned vector"
