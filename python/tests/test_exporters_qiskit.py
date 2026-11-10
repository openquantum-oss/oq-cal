"""Tests for the Qiskit Target exporter."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("qiskit")

from oq_cal.exporters.qiskit import to_qiskit_target
from oq_cal.models import OqCalDocument

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "oq-cal-docs"


def _load(name: str) -> OqCalDocument:
    return OqCalDocument.model_validate_json((FIXTURES / name).read_text())


@pytest.fixture
def per_qubit() -> OqCalDocument:
    return _load("valid_per_qubit.json")


@pytest.fixture
def full_depth() -> OqCalDocument:
    return _load("valid_full_depth.json")


@pytest.fixture
def aggregates_only() -> OqCalDocument:
    return _load("valid_aggregates_only.json")


def test_per_qubit_instruction_set(per_qubit):
    t = to_qiskit_target(per_qubit)
    # rb and interleaved_rb are benchmark instructions, not copies of x or cz.
    assert set(t.operation_names) == {"x", "cz", "measure", "rb", "interleaved_rb"}
    assert t.num_qubits == 8


def test_per_qubit_durations_and_errors(per_qubit):
    t = to_qiskit_target(per_qubit)
    x = t["x"][(0,)]
    assert x.duration == pytest.approx(3.2e-08)
    assert x.error == pytest.approx(0.00088)
    cz = t["cz"][(0, 1)]
    assert cz.duration == pytest.approx(2.4e-07)
    assert cz.error == pytest.approx(0.0121)
    # The rb benchmark is its own instruction. It is not copied onto x.
    # Its fidelity has no metric, so 1 - fidelity is an assumption.
    assert t["x"][(0,)].error == pytest.approx(0.00088)
    assert t["rb"][(0,)].error == pytest.approx(1 - 0.9991)
    assert t["interleaved_rb"][(0, 1)].error == pytest.approx(1 - 0.9879)


def test_per_qubit_qubit_properties(per_qubit):
    t = to_qiskit_target(per_qubit)
    qp0 = t.qubit_properties[0]
    assert qp0.t1 == pytest.approx(1.822e-05)
    assert qp0.t2 == pytest.approx(1.2044e-05)
    assert qp0.frequency == pytest.approx(4821335012.44)
    # $1 has no t2 -> None, not an error.
    assert t.qubit_properties[1].t2 is None


def test_measure_error_from_readout_fidelity(per_qubit):
    t = to_qiskit_target(per_qubit)
    m0 = t["measure"][(0,)]
    assert m0.error == pytest.approx(1 - 0.9445)
    m1 = t["measure"][(1,)]
    assert m1.error == pytest.approx(1 - 0.9335)


def test_full_depth_error_from_error_datum(full_depth):
    # full_depth gates carry only `error` (no duration) -> duration None.
    t = to_qiskit_target(full_depth)
    assert set(t.operation_names) == {"x", "cz", "measure"}
    x = t["x"][(0,)]
    assert x.error == pytest.approx(0.00088)
    assert x.duration is None


def test_process_fidelity_is_not_converted_to_an_error():
    doc = _load("valid_per_qubit.json")
    from oq_cal.models import Datum, Unit

    doc.gates[0].error = None
    doc.gates[0].fidelity = Datum(value=0.99, unit=Unit.DIMENSIONLESS, metric="process_fidelity")
    warnings: list[str] = []
    t = to_qiskit_target(doc, on_warning=warnings.append)
    assert t["x"][(0,)].error is None
    assert any("process_fidelity" in w for w in warnings)


def test_error_from_fidelity_when_no_error():
    doc = _load("valid_per_qubit.json")
    # Replace x gate error with a fidelity to exercise 1 - fidelity path.
    from oq_cal.models import Datum, Unit

    doc.gates[0].error = None
    doc.gates[0].fidelity = Datum(value=0.999, unit=Unit.DIMENSIONLESS)
    t = to_qiskit_target(doc)
    assert t["x"][(0,)].error == pytest.approx(1 - 0.999)


def test_aggregates_only_no_broadcast(aggregates_only):
    t = to_qiskit_target(aggregates_only)
    assert list(t.operation_names) == []
    assert t.num_qubits == 12


def test_aggregates_only_with_broadcast(aggregates_only):
    warnings: list[str] = []
    t = to_qiskit_target(
        aggregates_only, broadcast_aggregates=True, on_warning=warnings.append
    )
    # 1q set broadcast to all 12 qubits, 2q (cz) all-to-all.
    assert set(t.operation_names) == {"x", "sx", "rz", "cz"}
    assert len(t["x"]) == 12
    x0 = t["x"][(0,)]
    assert x0.duration == pytest.approx(0.00013)
    assert x0.error == pytest.approx(1 - 0.99981)
    cz = t["cz"][(0, 1)]
    assert cz.duration == pytest.approx(0.00097)
    assert cz.error == pytest.approx(1 - 0.9939)
    # all-to-all for 12 qubits = 12*11 ordered pairs
    assert len(t["cz"]) == 12 * 11
    # the all-to-all assumption is announced as a warning
    assert any("all-to-all" in w for w in warnings)


def test_invalid_gate_names_skipped_not_raised():
    doc = _load("valid_per_qubit.json")
    from oq_cal.models import Datum, GateEntry, Unit

    doc.gates.append(
        GateEntry(
            name="gpi2",  # native gate, no qiskit class
            qubits=["$0"],
            error=Datum(value=0.001, unit=Unit.DIMENSIONLESS),
        )
    )
    warnings: list[str] = []
    t = to_qiskit_target(doc, on_warning=warnings.append)
    assert "gpi2" not in t.operation_names
    assert any("gpi2" in w for w in warnings)
    # Known gates still mapped.
    assert "x" in t.operation_names


def test_logger_path_when_no_callback(caplog):
    doc = _load("valid_per_qubit.json")
    from oq_cal.models import GateEntry

    doc.gates.append(GateEntry(name="weirdgate", qubits=["$0"]))
    with caplog.at_level("WARNING", logger="oq_cal.exporters.qiskit"):
        to_qiskit_target(doc)
    assert any("weirdgate" in r.message for r in caplog.records)


def test_missing_num_qubits_raises_clear_valueerror():
    from oq_cal.models import Device, Header, OqCalDocument, Snapshot

    doc = OqCalDocument(
        oq_cal=Header(version="0.1"),
        device=Device(id="aws:ionq.forte-1"),  # no num_qubits
        snapshot=Snapshot(source="aws-braket"),
    )
    assert doc.device.num_qubits is None
    with pytest.raises(ValueError, match="num_qubits"):
        to_qiskit_target(doc)


def test_registered_in_registry():
    from oq_cal import registry

    assert "qiskit" in registry.list_formats()["exporters"]


# ---------------------------------------------------------------------------
# Dead-element handling (feedback 003): bad/unmeasured datums produce no entry.
# ---------------------------------------------------------------------------

from oq_cal.models import (  # noqa: E402
    Datum,
    Device,
    GateEntry,
    Header,
    QubitProperties,
    Readout,
    Snapshot,
)


def _doc_with_dead_elements() -> OqCalDocument:
    return OqCalDocument(
        oq_cal=Header(version="0.1"),
        device=Device(id="t", num_qubits=3),
        snapshot=Snapshot(source="t", captured_at="2026-10-31T00:00:00Z"),
        qubits={
            "$0": QubitProperties(
                readout=Readout(
                    fidelity=Datum(value=0.98, unit="dimensionless")
                )
            ),
            "$1": QubitProperties(
                readout=Readout(
                    fidelity=Datum(
                        value=0.5, unit="dimensionless", status="unmeasured"
                    )
                )
            ),
        },
        gates=[
            GateEntry(
                name="cz",
                qubits=["$0", "$1"],
                fidelity=Datum(value=0.99, unit="dimensionless"),
            ),
            GateEntry(
                name="cz",
                qubits=["$1", "$2"],
                fidelity=Datum(
                    value=0.5, unit="dimensionless", status="unmeasured"
                ),
            ),
        ],
    )


def test_dead_gate_edge_produces_no_instruction_entry():
    t = to_qiskit_target(_doc_with_dead_elements())
    cz = t["cz"]
    # Only the live edge ($0,$1) survives; the unmeasured ($1,$2) is skipped.
    assert (0, 1) in cz
    assert (1, 2) not in cz


def test_dead_readout_produces_no_measure_entry():
    t = to_qiskit_target(_doc_with_dead_elements())
    measure = t["measure"]
    assert (0,) in measure
    assert (1,) not in measure
