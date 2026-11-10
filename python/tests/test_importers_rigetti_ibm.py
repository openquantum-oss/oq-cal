"""Rigetti capabilities and IBM backend-properties importers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from oq_cal.importers.braket import BraketSchemaError, from_braket
from oq_cal.importers.ibm import IBMPropertiesError, from_ibm_properties
from oq_cal.importers.rigetti import from_braket_rigetti
from oq_cal.registry import get_importer
from oq_cal.validate import validate

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "sources"


def _rigetti() -> dict:
    return json.loads((FIXTURES / "rigetti" / "synthetic_rigetti_capabilities.json").read_text())


def _ibm() -> dict:
    return json.loads((FIXTURES / "ibm" / "synthetic_fictional_transmon2.json").read_text())


def test_rigetti_fixture_imports_connectivity_and_does_not_invent_gates():
    doc = from_braket_rigetti(_rigetti())
    assert validate(doc) == []
    assert doc.device.id == "braket-device"
    assert doc.device.vendor is None
    assert doc.device.num_qubits == 3
    assert doc.device.coupling_map == [
        ["$0", "$1"],
        ["$1", "$0"],
        ["$1", "$2"],
        ["$2", "$1"],
    ]
    assert doc.snapshot.captured_at == "2026-05-01T00:00:00Z"
    assert doc.snapshot.source_schema.endswith("rigetti_device_capabilities v2")
    assert doc.qubits["$0"].t1.value == pytest.approx(2e-5)
    assert doc.qubits["$0"].readout.fidelity.metric == "readout_fidelity"
    assert doc.qubits["$0"].readout.fidelity.value == pytest.approx(0.97)
    assert doc.gates is None
    rx = doc.defcals[0]
    assert rx.gate == "rx"
    assert rx.qubits == ["$0"]
    assert rx.params == {"frequency_hz": 4500000000}
    assert "dt" not in rx.params
    assert doc.extensions["braket"]["pulse"]["ports"]["q0_rf"]["dt"] == 1e-9


def test_rigetti_capabilities_only_has_no_calibration_table():
    payload = {
        "braketSchemaHeader": {
            "name": "braket.device_schema.rigetti.rigetti_device_capabilities",
            "version": "2",
        },
        "paradigm": {
            "qubitCount": 4,
            "connectivity": {"fullyConnected": True, "connectivityGraph": {}},
        },
    }
    doc = from_braket_rigetti(payload)
    assert validate(doc) == []
    assert doc.device.num_qubits == 4
    assert doc.device.coupling_map is None
    assert doc.qubits is None
    assert doc.gates is None
    assert doc.defcals is None


def test_rigetti_one_based_graph_shifts_with_labels():
    payload = {
        "braketSchemaHeader": {
            "name": "braket.device_schema.rigetti.rigetti_device_capabilities",
            "version": "2",
        },
        "paradigm": {
            "qubitCount": 2,
            "connectivity": {"connectivityGraph": {"1": ["2"], "2": ["1"]}},
        },
    }
    doc = from_braket_rigetti(payload)
    assert doc.device.num_qubits == 2
    assert doc.device.qubit_labels == {"$0": "1", "$1": "2"}
    assert doc.device.coupling_map == [["$0", "$1"], ["$1", "$0"]]
    assert doc.qubits is None


def test_braket_dispatches_on_the_schema_header():
    standardized = {
        "braketSchemaHeader": {
            "name": "braket.device_schema.standardized_gate_model_qpu_device_properties",
            "version": "1",
        }
    }
    doc = from_braket(standardized)
    assert doc.snapshot.source_schema.endswith(
        "standardized_gate_model_qpu_device_properties v1"
    )
    rigetti = from_braket(_rigetti())
    assert rigetti.snapshot.source_schema.endswith("rigetti_device_capabilities v2")
    assert get_importer("braket") is from_braket
    with pytest.raises(BraketSchemaError, match="rigetti_device_capabilities"):
        from_braket({"braketSchemaHeader": {"name": "nope", "version": "1"}})


def test_rigetti_specs_fill_a_missing_standard_error_only_when_the_value_matches():
    header = {
        "name": "braket.device_schema.rigetti.rigetti_device_capabilities",
        "version": "2",
    }
    standardized = {
        "braketSchemaHeader": {
            "name": "braket.device_schema.standardized_gate_model_qpu_device_properties",
            "version": "1",
        },
        "oneQubitProperties": {
            "0": {
                "T1": {"value": 3.6e-5, "unit": "S"},
                "T2": {"value": 2.1e-5, "unit": "S", "standardError": 9.0e-7},
            },
            "1": {"T1": {"value": 1.0e-5, "unit": "S"}},
        },
    }
    payload = {
        "braketSchemaHeader": header,
        "paradigm": {"qubitCount": 2, "connectivity": {"connectivityGraph": {}}},
        "standardized": standardized,
        "provider": {
            "specs": {
                "benchmarks": [
                    {
                        "name": "FreeInversionRecovery",
                        "sites": [
                            {
                                "node_ids": [0],
                                "characteristics": [{
                                    "name": "T1",
                                    "value": 3.6e-5,
                                    "error": 1.2e-6,
                                }],
                            },
                            {
                                "node_ids": [1],
                                "characteristics": [{
                                    "name": "T1",
                                    "value": 9.0e-5,
                                    "error": 1.0e-6,
                                }],
                            },
                        ],
                    },
                    {
                        "name": "FreeInductionDecay",
                        "sites": [{
                            "node_ids": [0],
                            "characteristics": [{
                                "name": "T2",
                                "value": 2.1e-5,
                                "error": 1.7e-6,
                            }],
                        }],
                    },
                ]
            }
        },
    }
    doc = from_braket_rigetti(payload)
    assert doc.qubits["$0"].t1.value == pytest.approx(3.6e-5)
    assert doc.qubits["$0"].t1.std_error == pytest.approx(1.2e-6)
    assert doc.qubits["$0"].t2.std_error == pytest.approx(9.0e-7)
    assert doc.qubits["$1"].t1.std_error is None
    assert validate(doc) == []


def test_rigetti_rejects_the_wrong_schema():
    with pytest.raises(BraketSchemaError):
        from_braket_rigetti(
            {
                "braketSchemaHeader": {
                    "name": "braket.device_schema.standardized_gate_model_qpu_device_properties",
                    "version": "1",
                }
            }
        )


def test_ibm_properties_units_direction_and_error_metric():
    doc = from_ibm_properties(_ibm())
    assert validate(doc) == []
    assert doc.device.id == "fictional-transmon-2"
    assert doc.device.vendor is None
    assert doc.device.num_qubits == 2
    assert doc.device.coupling_map == [["$0", "$1"]]
    assert doc.snapshot.captured_at == "2026-06-01T12:00:00Z"
    q0 = doc.qubits["$0"]
    assert q0.t1.value == pytest.approx(20e-6)
    assert q0.t1.updated_at == "2026-06-01T00:00:00+00:00"
    assert q0.t2.value == pytest.approx(15e-6)
    assert q0.frequency_01.value == pytest.approx(4.5e9)
    assert q0.anharmonicity.value == pytest.approx(-0.25e9)
    assert q0.readout.fidelity is None
    assert q0.readout.duration.value == pytest.approx(1e-6)
    assert q0.readout.confusion_matrix == [[0.75, 0.25], [0.5, 0.5]]
    assert q0.benchmarks[0].protocol == "readout"
    assert q0.benchmarks[0].error.value == pytest.approx(0.02)
    assert q0.benchmarks[0].error.metric == "assignment_error"
    assert q0.benchmarks[0].error.method is None
    x = next(g for g in doc.gates if g.name == "x")
    assert x.error.value == pytest.approx(0.0004)
    assert x.error.metric == "average_gate_error"
    assert x.error.method is None
    assert x.duration.value == pytest.approx(32e-9)
    cx = next(g for g in doc.gates if g.name == "cx")
    assert cx.qubits == ["$0", "$1"]
    assert doc.qubits["$1"].readout is None
    assert doc.qubits["$1"].benchmarks[0].error.value == pytest.approx(0.05)


def test_ibm_properties_requires_a_qubits_list():
    with pytest.raises(IBMPropertiesError):
        from_ibm_properties({"backend_name": "nope"})
