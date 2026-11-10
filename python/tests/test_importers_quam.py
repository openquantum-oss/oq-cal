"""Tests for the QUAM state.json importer."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from oq_cal.importers.quam import from_quam_state
from oq_cal.models import OqCalDocument
from oq_cal.validate import validate

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "sources" / "quam"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def test_fixture_imports_and_validates(quam_file):
    doc = from_quam_state(json.loads(quam_file.read_text()))
    assert validate(doc) == []


def test_qubits_extracted():
    doc = from_quam_state(_load("synthetic_state.json"))
    assert doc.device.num_qubits == 2
    assert doc.device.qubit_labels == {"$0": "q0", "$1": "q1"}
    q0 = doc.qubits["$0"]
    assert q0.t1.value == pytest.approx(1.822e-5)
    assert q0.t1.unit == "s"
    assert q0.t2.value == pytest.approx(1.2044e-5)  # T2ramsey
    assert q0.t2_echo.value == pytest.approx(2.498e-5)
    assert q0.frequency_01.value == pytest.approx(4821335012.0)
    assert q0.frequency_01.unit == "Hz"
    assert q0.anharmonicity.value == pytest.approx(-201443900.0)


def test_pulse_defcals_mapping():
    doc = from_quam_state(_load("synthetic_state.json"))
    by_key = {(d.gate, tuple(d.qubits)): d for d in doc.defcals}
    # x180 -> x, length 32 ns -> 3.2e-8 s
    x0 = by_key[("x", ("$0",))]
    assert x0.params["amp"] == pytest.approx(0.2041)
    assert x0.params["duration_s"] == pytest.approx(32e-9)
    assert x0.params["motzoi"] == pytest.approx(-0.11)
    # x90 -> sx
    sx0 = by_key[("sx", ("$0",))]
    assert sx0.params["amp"] == pytest.approx(0.1022)
    # readout -> measure, length 2000 ns -> 2e-6 s
    m0 = by_key[("measure", ("$0",))]
    assert m0.params["duration_s"] == pytest.approx(2e-6)
    # qubit_pair cz on coupler, resolved via #/ references
    cz = by_key[("cz", ("$0", "$1"))]
    assert cz.params["amp"] == pytest.approx(0.6612)
    assert cz.params["duration_s"] == pytest.approx(240e-9)


def test_never_raises_on_thin_tree():
    # A near-empty tree still yields a valid document.
    doc = from_quam_state({"__class__": "whatever.QuAM"})
    assert validate(doc) == []
    assert doc.device.num_qubits == 0
    assert doc.device.id == "quam-device"


def test_explicit_sample_rate_scales_length():
    """An explicit rate wins over the 1 GS/s default. 2 GS/s, 32 samples -> 16 ns."""
    tree = {
        "name": "fictional-quam",
        "sampling_rate": 2e9,
        "qubits": {
            "q0": {
                "__class__": "lab.Transmon",
                "id": 0,
                "xy": {"operations": {"x180": {"length": 32, "amplitude": 0.2}}},
            }
        },
    }
    doc = from_quam_state(tree)
    assert doc.defcals[0].params["duration_s"] == pytest.approx(16e-9)


def test_channel_rate_beats_root_rate():
    tree = {
        "sampling_rate": 2e9,
        "qubits": {
            "q0": {
                "__class__": "lab.Transmon",
                "id": 0,
                "xy": {
                    "sample_rate": 1e9,
                    "operations": {"x180": {"length": 32, "amplitude": 0.2}},
                },
            }
        },
    }
    doc = from_quam_state(tree)
    assert doc.defcals[0].params["duration_s"] == pytest.approx(32e-9)


def test_missing_fields_tolerated():
    tree = {
        "qubits": {
            "q0": {"__class__": "x.Transmon", "id": 0, "T1": 1e-5},
            "q1": {"__class__": "x.Transmon", "id": 1},  # no metrics at all
        }
    }
    doc = from_quam_state(tree)
    assert validate(doc) == []
    assert doc.qubits["$0"].t1.value == pytest.approx(1e-5)
    # q1 has no extractable metrics -> omitted from qubits map
    assert "$1" not in (doc.qubits or {})
    assert doc.device.num_qubits == 2  # still counted for addressing


def test_device_id_override_and_default():
    assert from_quam_state({}, device_id="my-dev").device.id == "my-dev"
    assert from_quam_state({}).device.id == "quam-device"


def test_unresolvable_reference_skipped():
    # A relative sibling reference (#../) must not crash extraction.
    tree = {
        "qubits": {
            "q0": {
                "__class__": "x.Transmon",
                "id": 0,
                "xy": {
                    "intermediate_frequency": "#../../q0/xy/intermediate_frequency",
                    "operations": {
                        "x180": {"amplitude": 0.2, "length": 32, "alpha": -0.1}
                    },
                },
            }
        }
    }
    doc = from_quam_state(tree)
    assert validate(doc) == []
    x0 = next(d for d in doc.defcals if d.gate == "x")
    assert x0.params["amp"] == pytest.approx(0.2)


def test_coupling_map_from_qubit_pair():
    """Fixture has one qubit_pair q0_q1 with a cz coupler op -> one undirected
    pair -> two directed coupling_map pairs. q0=$0, q1=$1."""
    doc = from_quam_state(_load("synthetic_state.json"))
    assert doc.device.coupling_map == [["$0", "$1"], ["$1", "$0"]]
    assert validate(doc) == []


def test_no_coupling_map_without_pair_evidence():
    """A thin tree with no 2q evidence emits no coupling_map."""
    doc = from_quam_state({"qubits": {}})
    assert doc.device.coupling_map is None


def test_extensions_verbatim():
    payload = _load("synthetic_state.json")
    doc = from_quam_state(payload)
    assert doc.extensions["quam"] == payload


def test_round_trip_json():
    doc = from_quam_state(_load("synthetic_state.json"))
    reparsed = OqCalDocument.model_validate_json(doc.model_dump_json())
    assert validate(reparsed) == []
