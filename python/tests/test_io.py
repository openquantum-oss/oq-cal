"""Tests for the canonical JSON writer (oq_cal.io.to_canonical_json)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from oq_cal.io import to_canonical_json
from oq_cal.models import OqCalDocument

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "oq-cal-docs"


def _load(name: str) -> OqCalDocument:
    return OqCalDocument.model_validate_json((FIXTURES / name).read_text())


@pytest.fixture
def doc() -> OqCalDocument:
    return _load("valid_full_depth.json")


def test_trailing_newline(doc):
    out = to_canonical_json(doc)
    assert out.endswith("}\n")
    # exactly one trailing newline
    assert not out.endswith("}\n\n")


def test_two_space_indent(doc):
    out = to_canonical_json(doc)
    lines = out.splitlines()
    # the top-level keys are indented by exactly two spaces
    assert any(line.startswith('  "oq-cal"') for line in lines)
    assert not any(line.startswith('    "oq-cal"') for line in lines)


def test_excludes_none(doc):
    out = to_canonical_json(doc)
    # Optional model fields are omitted. This fixture has no extension nulls.
    assert ": null" not in out


def test_extensions_keep_json_null():
    doc = OqCalDocument.model_validate(
        {
            "oq-cal": {"name": "oq-cal.device_calibration", "version": "0.1"},
            "device": {"id": "d", "vendor": None},
            "snapshot": {"source": "test"},
            "extensions": {"boulder_opal": {"qubit_cal": None, "nested": {"err_minus": None, "value": 1}}},
        }
    )
    data = json.loads(to_canonical_json(doc))
    assert "vendor" not in data["device"]
    assert data["extensions"]["boulder_opal"]["qubit_cal"] is None
    assert data["extensions"]["boulder_opal"]["nested"]["err_minus"] is None
    assert data["extensions"]["boulder_opal"]["nested"]["value"] == 1


def test_round_trips_structurally(doc):
    out = to_canonical_json(doc)
    reparsed = OqCalDocument.model_validate_json(out)
    assert json.loads(to_canonical_json(reparsed)) == json.loads(out)


def test_deterministic(doc):
    assert to_canonical_json(doc) == to_canonical_json(doc)


def test_field_order_not_sorted(doc):
    """Keys follow model declaration order, not alphabetical order."""
    out = to_canonical_json(doc)
    data = json.loads(out)
    # the header 'oq-cal' section precedes 'device' which precedes 'snapshot' in
    # model-declaration order; sorted order would put 'device' first.
    top_keys = list(data.keys())
    assert top_keys.index("oq-cal") < top_keys.index("device")
    assert top_keys.index("device") < top_keys.index("snapshot")


def test_utf8_not_ascii_escaped():
    """Non-ASCII characters are emitted verbatim, not \\uXXXX-escaped."""
    doc = OqCalDocument.model_validate(
        {
            "oq-cal": {"name": "oq-cal.device_calibration", "version": "0.1"},
            "device": {"id": "synthetic:µ-device", "vendor": "Ωmega"},
            "snapshot": {"source": "test"},
        }
    )
    out = to_canonical_json(doc)
    assert "µ-device" in out
    assert "Ωmega" in out
    assert "\\u" not in out


def test_matches_cli_convert_output(doc, tmp_path):
    """The CLI 'convert ... --to oq-cal' writes exactly the canonical form."""
    from click.testing import CliRunner

    from oq_cal.cli import main

    src = FIXTURES / "valid_full_depth.json"
    out = tmp_path / "out.oq-cal.json"
    r = CliRunner().invoke(main, ["convert", str(src), "-o", str(out)])
    assert r.exit_code == 0, r.output
    expected = to_canonical_json(_load("valid_full_depth.json"))
    assert out.read_text(encoding="utf-8") == expected
