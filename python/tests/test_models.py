"""Tests for the pydantic models: all valid oq-cal fixtures load and round-trip."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from oq_cal import Datum, Device, Header, OqCalDocument, Status, Unit


def test_identity_only_document():
    doc = OqCalDocument.model_validate(
        {
            "oq-cal": {"name": "oq-cal.device_calibration", "version": "0.1"},
            "device": {"id": "x", "num_qubits": 2},
            "snapshot": {"source": "test"},
        }
    )
    assert doc.device.num_qubits == 2
    assert doc.qubits is None


def test_valid_fixtures_load(oq_cal_valid_file):
    text = oq_cal_valid_file.read_text()
    doc = OqCalDocument.model_validate_json(text)
    assert doc.oq_cal.name == "oq-cal.device_calibration"
    assert doc.oq_cal.version == "0.1"


def test_valid_fixtures_round_trip(oq_cal_valid_file):
    text = oq_cal_valid_file.read_text()
    doc = OqCalDocument.model_validate_json(text)
    # Re-serialise, re-parse, and confirm the model is stable.
    reparsed = OqCalDocument.model_validate_json(doc.model_dump_json(exclude_none=True))
    assert reparsed == doc


def test_datum_shapes():
    bare = Datum(value=1.0, unit="s")
    assert bare.std_error is None
    structured = Datum(
        value=1.5e-5,
        unit="s",
        err_minus=1e-7,
        err_plus=2e-7,
        status="good",
        updated_at="2026-01-01T00:00:00+00:00",
    )
    assert structured.status == Status.GOOD.value
    assert structured.unit == Unit.SECOND.value


def test_header_rejects_bad_name():
    with pytest.raises(ValidationError):
        Header(name="something.else", version="0.1")


def test_header_rejects_bad_version():
    with pytest.raises(ValidationError):
        Header(version="0.1.0")


def test_device_num_qubits_optional():
    # num_qubits is OPTIONAL (spec §4): aggregates-only sources omit it.
    dev = Device(id="x")
    assert dev.num_qubits is None
    # When present it must still be a non-negative integer.
    assert Device(id="x", num_qubits=0).num_qubits == 0
    with pytest.raises(ValidationError):
        Device(id="x", num_qubits=-1)


def test_full_depth_sections_present(fixtures_dir):
    doc = OqCalDocument.model_validate_json(
        (fixtures_dir / "oq-cal-docs" / "valid_full_depth.json").read_text()
    )
    assert doc.aggregates is not None
    assert doc.qubits and "$0" in doc.qubits
    assert doc.gates and any(g.name == "cz" for g in doc.gates)
    assert doc.defcals and any(d.gate == "measure" for d in doc.defcals)
    # classifier survives
    assert doc.qubits["$0"].readout.classifier.type == "linear_iq"


def test_extra_fields_preserved():
    doc = OqCalDocument.model_validate(
        {
            "oq-cal": {"name": "oq-cal.device_calibration", "version": "0.1"},
            "device": {"id": "x", "num_qubits": 1, "custom_field": 7},
            "snapshot": {"source": "test"},
        }
    )
    dumped = json.loads(doc.model_dump_json())
    assert dumped["device"]["custom_field"] == 7
