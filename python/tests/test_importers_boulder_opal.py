"""Tests for the Boulder Opal calibration snapshot (Q-CTRL product) importer."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from oq_cal.diff import diff
from oq_cal.importers.boulder_opal import from_boulder_opal
from oq_cal.models import OqCalDocument
from oq_cal.validate import validate

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "sources" / "boulder-opal"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def test_fixture_imports_and_validates(boulder_opal_file):
    doc = from_boulder_opal(json.loads(boulder_opal_file.read_text()))
    assert validate(doc) == []


def test_qubit_labels_and_num_qubits():
    doc = from_boulder_opal(_load("synthetic_acme_transmon8.json"))
    assert doc.device.num_qubits == 6  # roster qA0..qA5, not a compacted subset
    assert doc.device.qubit_labels["$0"] == "qA0"
    assert doc.device.id == "acme-transmon-8"
    assert doc.device.model == "acme-transmon-8"
    assert doc.snapshot.captured_at == "2026-09-02T11:20:05.512300+00:00"


def test_mixed_datum_shapes_normalized():
    doc = from_boulder_opal(_load("synthetic_acme_transmon8.json"))
    q0 = doc.qubits["$0"]
    # freq_01 structured with symmetric err bars (Hz)
    assert q0.frequency_01.unit == "Hz"
    assert q0.frequency_01.value == pytest.approx(4821335012.44)
    assert q0.frequency_01.err_minus == pytest.approx(5120.0)
    assert q0.frequency_01.err_plus == pytest.approx(5120.0)
    # anharm (Hz, negative)
    assert q0.anharmonicity.value == pytest.approx(-201443900.0)
    # t1 duration dict 18220 ns -> 1.822e-5 s, err bars scaled to s
    assert q0.t1.unit == "s"
    assert q0.t1.value == pytest.approx(1.822e-5)
    assert q0.t1.status == "good"
    # t2 with calibration_status approximate
    assert q0.t2.status == "approximate"


def test_classifier_to_readout():
    doc = from_boulder_opal(_load("synthetic_acme_transmon8.json"))
    ro = doc.qubits["$0"].readout
    assert ro.confusion_matrix == [[0.961, 0.039], [0.072, 0.928]]
    # fidelity = mean of diagonal
    assert ro.fidelity.value == pytest.approx((0.961 + 0.928) / 2)
    assert ro.fidelity.method == "confusion_matrix_diagonal"
    assert ro.fidelity.metric == "readout_fidelity"
    assert ro.classifier.type == "linear_iq"
    assert ro.classifier.threshold == pytest.approx(0.2041)
    assert ro.classifier.status == "calibrated"


def test_defcals_mapping():
    doc = from_boulder_opal(_load("synthetic_acme_transmon8.json"))
    by_key = {(d.gate, tuple(d.qubits)): d for d in doc.defcals}
    x0 = by_key[("x", ("$0",))]
    assert x0.params["duration_s"] == pytest.approx(3.2e-8)
    assert x0.params["amp"] == pytest.approx(0.2041)
    assert x0.params["motzoi"] == pytest.approx(-0.11)
    assert x0.params["frequency_hz"] == pytest.approx(4821335012.0)
    # cz across the pair
    cz = by_key[("cz", ("$0", "$1"))]
    assert cz.params["frequency_hz"] == pytest.approx(4.861e9)
    # measure carries integration_time_s and preserves role
    meas = by_key[("measure", ("$0",))]
    assert meas.params["integration_time_s"] == pytest.approx(1.8e-6)
    assert meas.params["role"] == "readout"


def test_gate_errors_to_gates():
    doc = from_boulder_opal(_load("synthetic_acme_transmon8.json"))
    x = next(g for g in doc.gates if g.name == "x" and g.qubits == ["$0"])
    assert x.error.value == pytest.approx(0.00088)
    assert x.error.status == "good"
    cz = next(g for g in doc.gates if g.name == "cz" and g.qubits == ["$0", "$1"])
    assert cz.error.value == pytest.approx(0.0121)
    assert cz.error.status == "approximate"


def test_resonator_and_port_not_in_core():
    doc = from_boulder_opal(_load("synthetic_acme_transmon8.json"))
    # Only transmon-derived qubit refs appear ($0, $1); resonators/ports are
    # not core qubits but survive in extensions.
    assert set(doc.qubits) == {"$0", "$1"}
    assert "rA0" in doc.extensions["boulder_opal"]["components"]


def test_coupling_map_from_2q_evidence_both_directions():
    """Boulder Opal fixture: cz:qA0_qA1 defcal + [qA0,qA1] gate_error -> one undirected
    pair -> two directed coupling_map pairs. qA0=$0, qA1=$1."""
    doc = from_boulder_opal(_load("synthetic_acme_transmon8.json"))
    cm = doc.device.coupling_map
    assert cm == [["$0", "$1"], ["$1", "$0"]]
    assert validate(doc) == []


def test_extensions_verbatim():
    payload = _load("synthetic_acme_transmon8.json")
    doc = from_boulder_opal(payload)
    assert doc.extensions["boulder_opal"] == payload


def test_round_trip_json():
    doc = from_boulder_opal(_load("synthetic_acme_transmon8.json"))
    reparsed = OqCalDocument.model_validate_json(doc.model_dump_json())
    assert validate(reparsed) == []


def test_lumen_components_fallback():
    """No qubit_cal. Duration-shaped errors, transposed confusion, drive frequency."""
    doc = from_boulder_opal(_load("synthetic_lumen_components.json"))
    assert validate(doc) == []
    assert doc.device.id == "lumen-demo-4"
    assert doc.device.model == "lumen-demo-4"
    assert doc.device.vendor is None
    assert doc.device.num_qubits == 3
    assert doc.device.qubit_labels == {"$0": "q0", "$1": "q1", "$2": "q2"}
    assert doc.device.enabled_qubits == ["$0", "$1"]
    assert doc.snapshot.captured_at == "2026-03-01T12:00:00+00:00"
    assert doc.gates is None
    assert doc.device.coupling_map is None
    # q2 is measured and stays on the roster, but it is not offered.
    assert "$2" not in doc.device.enabled_qubits
    assert doc.qubits["$2"].t1.value == pytest.approx(1.1e-5)

    q0 = doc.qubits["$0"]
    assert q0.t1.value == pytest.approx(2.0e-5)
    assert q0.t1.err_minus == pytest.approx(4.0e-7)
    assert q0.t1.status == "good"
    assert q0.t1.updated_at == "2026-03-01T11:00:00+00:00"
    assert q0.t2 is None
    raw_cm = doc.extensions["boulder_opal"]["classifiers"]["q0"]["confusion_matrix"]
    assert q0.readout.confusion_matrix == [list(col) for col in zip(*raw_cm)]
    assert q0.readout.confusion_matrix == [[0.9, 0.1], [0.25, 0.75]]

    by_key = {(d.gate, tuple(d.qubits)): d for d in doc.defcals}
    raw_x = doc.extensions["boulder_opal"]["defcals"]["x:q0"]["frequency"]
    raw_m = doc.extensions["boulder_opal"]["defcals"]["measure:q0"]["frequency"]
    assert raw_x == raw_m
    assert by_key[("x", ("$0",))].params["frequency_hz"] == pytest.approx(4500000000.0)
    assert by_key[("sx", ("$0",))].params["frequency_hz"] == pytest.approx(4500000000.0)
    assert by_key[("measure", ("$0",))].params["frequency_hz"] == pytest.approx(raw_m)
    assert by_key[("measure", ("$0",))].params["program"] == "OPENQASM 3.0; // fictional"


def test_lumen_qubit_cal_preferred():
    doc = from_boulder_opal(_load("synthetic_lumen_qubit_cal.json"))
    assert validate(doc) == []
    assert doc.device.id == "lumen-demo-4"
    assert doc.device.num_qubits == 3
    assert doc.device.qubit_labels["$0"] == "q0"
    assert doc.device.qubit_labels["$2"] == "q2"
    # operational flags, not the enabled_qubits list: q1 is offered, q2 is not.
    assert doc.device.enabled_qubits == ["$0", "$1"]
    assert doc.snapshot.captured_at == "2026-04-15T09:30:00+00:00"
    assert set(doc.qubits) == {"$0", "$2"}
    assert doc.gates is None
    assert doc.device.coupling_map is None

    q0 = doc.qubits["$0"]
    assert q0.t1.value == pytest.approx(4.0e-5)
    assert q0.t1.err_minus == pytest.approx(1.0e-6)
    assert q0.t1.status == "approximate"
    assert q0.t1.updated_at == "2026-04-15T09:00:00+00:00"
    assert q0.frequency_01.value == pytest.approx(4600000000.0)
    assert q0.anharmonicity is None
    assert doc.qubits["$2"].t1.value == pytest.approx(1.1e-5)
    assert doc.qubits["$2"].t1.status == "good"

    by_key = {(d.gate, tuple(d.qubits)): d for d in doc.defcals}
    assert by_key[("x", ("$0",))].params["frequency_hz"] == pytest.approx(4600000000.0)
    assert by_key[("measure", ("$0",))].params["frequency_hz"] == pytest.approx(7100000000.0)
    stored = q0.readout.confusion_matrix
    assert [sum(row) for row in stored] == pytest.approx([1.0, 1.0])


def test_lumen_drift_marks_t1_and_status():
    earlier = from_boulder_opal(_load("synthetic_lumen_components.json"))
    later = from_boulder_opal(_load("synthetic_lumen_qubit_cal.json"))
    report = diff(earlier, later)
    t1 = next(e for e in report.entries if e.path == "qubits.$0.t1")
    assert t1.significance == "major"
    assert t1.a_value == pytest.approx(2.0e-5)
    assert t1.b_value == pytest.approx(4.0e-5)
    assert t1.rel_change == pytest.approx(1.0)
    status = next(e for e in report.entries if e.path == "qubits.$0.t1.status")
    assert status.significance == "major"
    assert status.a_status == "good"
    assert status.b_status == "approximate"
    assert status.a_value is None
    ranked = [e.path for e in report.worst_offenders(len(report.entries))]
    assert ranked.index("qubits.$0.t1") < ranked.index("qubits.$0.t1.status")
