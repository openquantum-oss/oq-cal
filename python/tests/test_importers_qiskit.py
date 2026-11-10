"""Tests for the Qiskit Target importer."""

from __future__ import annotations

import pytest

from oq_cal.importers.qiskit import from_qiskit_target
from oq_cal.models import OqCalDocument
from oq_cal.validate import validate

qiskit = pytest.importorskip("qiskit")

from qiskit.circuit.library import CZGate, Measure, SXGate, XGate  # noqa: E402
from qiskit.transpiler import (  # noqa: E402
    InstructionProperties,
    QubitProperties,
    Target,
)


def _build_target() -> Target:
    target = Target(
        num_qubits=3,
        qubit_properties=[
            QubitProperties(t1=3.0e-5, t2=2.0e-5, frequency=5.0e9),
            QubitProperties(t1=4.0e-5, t2=3.0e-5, frequency=5.1e9),
            QubitProperties(t1=3.5e-5, t2=2.5e-5, frequency=5.2e9),
        ],
    )
    target.add_instruction(
        XGate(),
        {
            (0,): InstructionProperties(duration=3.2e-8, error=0.001),
            (1,): InstructionProperties(duration=3.2e-8, error=0.0012),
            (2,): InstructionProperties(duration=3.2e-8, error=0.0011),
        },
    )
    target.add_instruction(
        SXGate(),
        {(0,): InstructionProperties(duration=1.6e-8, error=0.0005)},
    )
    target.add_instruction(
        CZGate(),
        {
            (0, 1): InstructionProperties(duration=2.4e-7, error=0.012),
            (1, 2): InstructionProperties(duration=2.5e-7, error=0.013),
        },
    )
    target.add_instruction(
        Measure(),
        {
            (0,): InstructionProperties(duration=2.0e-6, error=0.02),
            (1,): InstructionProperties(duration=2.0e-6, error=0.03),
        },
    )
    return target


def test_imports_and_validates():
    doc = from_qiskit_target(_build_target(), device_id="test-qpu", vendor="Acme")
    assert validate(doc) == []
    assert doc.device.id == "test-qpu"
    assert doc.device.vendor == "Acme"
    assert doc.device.num_qubits == 3


def test_qubit_properties_mapping():
    doc = from_qiskit_target(_build_target(), device_id="test-qpu")
    q0 = doc.qubits["$0"]
    assert q0.t1.value == pytest.approx(3.0e-5)
    assert q0.t1.unit == "s"
    assert q0.t2.value == pytest.approx(2.0e-5)
    assert q0.frequency_01.value == pytest.approx(5.0e9)
    assert q0.frequency_01.unit == "Hz"


def test_gate_instruction_mapping():
    doc = from_qiskit_target(_build_target(), device_id="test-qpu")
    x0 = next(g for g in doc.gates if g.name == "x" and g.qubits == ["$0"])
    assert x0.error.value == pytest.approx(0.001)
    assert x0.error.unit == "dimensionless"
    assert x0.duration.value == pytest.approx(3.2e-8)
    assert x0.duration.unit == "s"
    cz = next(g for g in doc.gates if g.name == "cz" and g.qubits == ["$0", "$1"])
    assert cz.error.value == pytest.approx(0.012)
    assert cz.duration.value == pytest.approx(2.4e-7)


def test_measure_folds_into_readout():
    doc = from_qiskit_target(_build_target(), device_id="test-qpu")
    # measure must NOT appear as a gate
    assert all(g.name != "measure" for g in doc.gates)
    ro = doc.qubits["$0"].readout
    assert ro.fidelity.value == pytest.approx(1.0 - 0.02)
    assert ro.fidelity.method == "qiskit_target"
    assert ro.duration.value == pytest.approx(2.0e-6)


def test_no_extensions_payload():
    doc = from_qiskit_target(_build_target(), device_id="test-qpu")
    # Target is not JSON-serializable -> no verbatim extensions payload.
    assert doc.extensions is None


def test_round_trip_json():
    doc = from_qiskit_target(_build_target(), device_id="test-qpu")
    reparsed = OqCalDocument.model_validate_json(doc.model_dump_json())
    assert validate(reparsed) == []


def test_registry_wrapper_rejects_dict():
    from oq_cal.registry import get_importer

    fn = get_importer("qiskit-target")
    with pytest.raises(TypeError):
        fn({})


def test_all_importers_registered():
    from oq_cal.registry import list_formats

    importers = set(list_formats()["importers"])
    assert {
        "braket",
        "boulder-opal",
        "ibm-properties",
        "quam-state",
        "qiskit-target",
    } <= importers
    assert "braket-standardized" not in importers
    assert "braket-rigetti" not in importers
