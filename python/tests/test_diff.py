"""Tests for the calibration drift engine."""

from __future__ import annotations

import pytest

from oq_cal.diff import MAJOR_REL, MINOR_REL, diff
from oq_cal.models import (
    Datum,
    Device,
    GateEntry,
    Header,
    OqCalDocument,
    QubitProperties,
    Snapshot,
    Unit,
)


def _doc(qubits=None, gates=None, defcals=None, aggregates=None, num_qubits=4):
    return OqCalDocument(
        oq_cal=Header(version="0.1"),
        device=Device(id="synthetic:test", num_qubits=num_qubits),
        snapshot=Snapshot(source="synthetic"),
        qubits=qubits,
        gates=gates,
        defcals=defcals,
        aggregates=aggregates,
    )


def _s(value: float) -> Datum:
    return Datum(value=value, unit=Unit.SECOND)


def _dl(value: float) -> Datum:
    return Datum(value=value, unit=Unit.DIMENSIONLESS)


def _entry(d, path):
    for e in d.entries:
        if e.path == path:
            return e
    raise AssertionError(f"no diff entry for {path!r}; have {[e.path for e in d.entries]}")


def test_t1_major_drop():
    a = _doc(qubits={"$0": QubitProperties(t1=_s(100e-6))})
    b = _doc(qubits={"$0": QubitProperties(t1=_s(70e-6))})  # -30%
    d = diff(a, b)
    e = _entry(d, "qubits.$0.t1")
    assert e.a_value == pytest.approx(100e-6)
    assert e.b_value == pytest.approx(70e-6)
    assert e.rel_change == pytest.approx(-0.30)
    assert e.significance == "major"


def test_small_fidelity_change_is_noise():
    # 0.99 -> 0.9801 is -1% -> below minor threshold -> noise
    a = _doc(gates=[GateEntry(name="x", qubits=["$0"], fidelity=_dl(0.99))])
    b = _doc(gates=[GateEntry(name="x", qubits=["$0"], fidelity=_dl(0.9801))])
    d = diff(a, b)
    e = _entry(d, "gates.x@$0.fidelity")
    assert abs(e.rel_change) == pytest.approx(0.01, abs=1e-6)
    assert e.significance == "noise"


def test_minor_boundary():
    # exactly above MINOR_REL but below MAJOR_REL
    a = _doc(qubits={"$0": QubitProperties(t1=_s(100.0))})
    b = _doc(qubits={"$0": QubitProperties(t1=_s(100.0 * (1 + MINOR_REL + 0.01)))})
    d = diff(a, b)
    assert _entry(d, "qubits.$0.t1").significance == "minor"


def test_major_boundary():
    a = _doc(qubits={"$0": QubitProperties(t1=_s(100.0))})
    b = _doc(qubits={"$0": QubitProperties(t1=_s(100.0 * (1 + MAJOR_REL + 0.01)))})
    d = diff(a, b)
    assert _entry(d, "qubits.$0.t1").significance == "major"


def test_added_qubit_datum_is_major():
    a = _doc(qubits={"$0": QubitProperties(t1=_s(100e-6))})
    b = _doc(
        qubits={
            "$0": QubitProperties(t1=_s(100e-6)),
            "$1": QubitProperties(t1=_s(90e-6)),
        }
    )
    d = diff(a, b)
    e = _entry(d, "qubits.$1.t1")
    assert e.a_value is None
    assert e.b_value == pytest.approx(90e-6)
    assert e.rel_change is None
    assert e.significance == "major"


def test_removed_datum_is_major():
    a = _doc(qubits={"$0": QubitProperties(t1=_s(100e-6), t2=_s(50e-6))})
    b = _doc(qubits={"$0": QubitProperties(t1=_s(100e-6))})  # t2 gone
    d = diff(a, b)
    e = _entry(d, "qubits.$0.t2")
    assert e.a_value == pytest.approx(50e-6)
    assert e.b_value is None
    assert e.significance == "major"


def test_unchanged_datum_is_noise():
    a = _doc(qubits={"$0": QubitProperties(t1=_s(100e-6))})
    b = _doc(qubits={"$0": QubitProperties(t1=_s(100e-6))})
    d = diff(a, b)
    assert _entry(d, "qubits.$0.t1").significance == "noise"
    assert _entry(d, "qubits.$0.t1").abs_change == 0


def test_defcal_params_compared_numerically():
    a = _doc(defcals=[{"gate": "x", "qubits": ["$0"], "params": {"amp": 0.20, "label": "p"}}])
    b = _doc(defcals=[{"gate": "x", "qubits": ["$0"], "params": {"amp": 0.30, "label": "p"}}])
    # pydantic will coerce dicts into Defcal
    d = diff(a, b)
    e = _entry(d, "defcals.x@$0.params.amp")
    assert e.rel_change == pytest.approx(0.5)
    assert e.significance == "major"
    # non-numeric param "label" is ignored
    assert not any(p.endswith("params.label") for p in [x.path for x in d.entries])


def test_gate_keyed_by_name_and_qubits_resists_reorder():
    g1 = GateEntry(name="x", qubits=["$0"], error=_dl(0.001))
    g2 = GateEntry(name="cz", qubits=["$0", "$1"], error=_dl(0.01))
    a = _doc(gates=[g1, g2])
    b = _doc(gates=[g2, g1])  # reordered, same values
    d = diff(a, b)
    # No add/remove churn; both gates unchanged -> all noise.
    assert all(e.significance == "noise" for e in d.entries)
    assert _entry(d, "gates.x@$0.error")
    assert _entry(d, "gates.cz@$0,$1.error")


def test_summary_counts_and_worst_offenders():
    a = _doc(
        qubits={
            "$0": QubitProperties(t1=_s(100e-6)),
            "$1": QubitProperties(t1=_s(100e-6)),
        }
    )
    b = _doc(
        qubits={
            "$0": QubitProperties(t1=_s(50e-6)),  # -50% major
            "$1": QubitProperties(t1=_s(96e-6)),  # -4% noise
        }
    )
    d = diff(a, b)
    counts = d.counts
    assert counts["major"] == 1
    assert counts["noise"] == 1
    worst = d.worst_offenders(1)[0]
    assert worst.path == "qubits.$0.t1"
    s = d.summary()
    assert s["total"] == 2
    assert s["counts"]["major"] == 1


def test_status_change_is_major_and_does_not_outrank_a_value():
    good = Datum(value=1e-5, unit=Unit.SECOND, status="good")
    moved = Datum(value=2e-5, unit=Unit.SECOND, status="approximate")
    a = _doc(qubits={"$0": QubitProperties(t1=good)})
    b = _doc(qubits={"$0": QubitProperties(t1=moved)})
    d = diff(a, b)
    status = _entry(d, "qubits.$0.t1.status")
    assert status.significance == "major"
    assert status.a_status == "good"
    assert status.b_status == "approximate"
    assert status.a_value is None
    assert status.rel_change is None
    assert d.worst_offenders(1)[0].path == "qubits.$0.t1"


def test_metric_or_method_change_is_major_when_the_number_is_unchanged():
    a = _doc(
        gates=[
            GateEntry(
                name="x",
                qubits=["$0"],
                fidelity=Datum(
                    value=0.99,
                    unit=Unit.DIMENSIONLESS,
                    method="rb",
                    metric="process_fidelity",
                ),
            )
        ]
    )
    b = _doc(
        gates=[
            GateEntry(
                name="x",
                qubits=["$0"],
                fidelity=Datum(
                    value=0.99,
                    unit=Unit.DIMENSIONLESS,
                    method="readout",
                    metric="average_gate_fidelity",
                ),
            )
        ]
    )
    d = diff(a, b)
    metric = _entry(d, "gates.x@$0.fidelity.metric")
    method = _entry(d, "gates.x@$0.fidelity.method")
    assert metric.significance == "major"
    assert metric.a_status == "process_fidelity"
    assert metric.b_status == "average_gate_fidelity"
    assert metric.a_value is None
    assert method.a_status == "rb"
    assert method.b_status == "readout"
    value = _entry(d, "gates.x@$0.fidelity")
    assert value.significance == "noise"
    assert value.rel_change == pytest.approx(0)


def test_unchanged_status_is_not_an_entry():
    datum = Datum(value=1e-5, unit=Unit.SECOND, status="good")
    a = _doc(qubits={"$0": QubitProperties(t1=datum)})
    b = _doc(qubits={"$0": QubitProperties(t1=Datum(value=1e-5, unit=Unit.SECOND, status="good"))})
    d = diff(a, b)
    assert not any(e.path.endswith(".status") for e in d.entries)
    assert d.counts["major"] == 0


def test_zero_baseline_handled():
    # anharmonicity moving away from 0 -> rel undefined -> major if abs change nonzero
    a = _doc(qubits={"$0": QubitProperties(anharmonicity=Datum(value=0.0, unit=Unit.HERTZ))})
    b = _doc(qubits={"$0": QubitProperties(anharmonicity=Datum(value=-2e8, unit=Unit.HERTZ))})
    d = diff(a, b)
    e = _entry(d, "qubits.$0.anharmonicity")
    assert e.rel_change is None
    assert e.significance == "major"
