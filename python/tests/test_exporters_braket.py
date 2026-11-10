"""Tests for the Braket standardized-properties exporter."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from oq_cal.exporters.braket import to_braket, to_braket_standardized
from oq_cal.importers.braket import from_braket
from oq_cal.models import (
    Datum,
    Device,
    GateEntry,
    Header,
    OqCalDocument,
    QubitProperties,
    Readout,
    Snapshot,
    Unit,
)

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "oq-cal-docs"


def _load(name: str) -> OqCalDocument:
    return OqCalDocument.model_validate_json((FIXTURES / name).read_text())


@pytest.fixture
def per_qubit() -> OqCalDocument:
    return _load("valid_per_qubit.json")


def test_schema_header(per_qubit):
    d = to_braket_standardized(per_qubit)
    hdr = d["braketSchemaHeader"]
    assert hdr["name"] == (
        "braket.device_schema.standardized_gate_model_qpu_device_properties"
    )
    assert hdr["version"] == "1"


def test_one_qubit_keys_and_units(per_qubit):
    d = to_braket_standardized(per_qubit)
    one = d["oneQubitProperties"]
    assert set(one) == {"0", "1"}
    q0 = one["0"]
    assert q0["T1"] == {"value": pytest.approx(1.822e-05), "unit": "S"}
    # $0 has t2_echo preferred over t2.
    assert q0["T2"] == {"value": pytest.approx(2.498e-05), "unit": "S"}
    # $1 has no t2 at all -> no T2 key.
    assert "T2" not in one["1"]


def test_readout_and_confusion_matrix_fidelity_entries(per_qubit):
    d = to_braket_standardized(per_qubit)
    fids = d["oneQubitProperties"]["0"]["oneQubitFidelity"]
    by_type = {f["fidelityType"]["name"]: f["fidelity"] for f in fids}
    assert by_type["READOUT"] == pytest.approx(0.9445)
    # confusion matrix [[0.961,0.039],[0.072,0.928]]
    assert by_type["READOUT_ERROR_0_TO_1"] == pytest.approx(0.039)
    assert by_type["READOUT_ERROR_1_TO_0"] == pytest.approx(0.072)
    # single-qubit RB benchmark carried through with its standardError
    rb = next(f for f in fids if f["fidelityType"]["name"] == "RANDOMIZED_BENCHMARKING")
    assert rb["fidelity"] == pytest.approx(0.9991)
    assert rb["standardError"] == pytest.approx(0.00012)


def test_two_qubit_properties(per_qubit):
    d = to_braket_standardized(per_qubit)
    two = d["twoQubitProperties"]
    assert set(two) == {"0-1"}
    gatefids = two["0-1"]["twoQubitGateFidelity"]
    # cz error 0.0121 has no metric, so it is not inverted into a fidelity.
    # The interleaved_rb benchmark is a named protocol and is exported.
    by = {(f["gateName"], f["fidelityType"]["name"]): f["fidelity"] for f in gatefids}
    assert ("CZ", "RANDOMIZED_BENCHMARKING") not in by
    assert ("CZ", "INTERLEAVED_RANDOMIZED_BENCHMARKING") in by
    assert by[("CZ", "INTERLEAVED_RANDOMIZED_BENCHMARKING")] == pytest.approx(0.9879)


def test_pure_dict_no_braket_dependency(per_qubit):
    d = to_braket_standardized(per_qubit)
    assert isinstance(d, dict)
    import json

    # round-trippable through plain JSON (no custom objects)
    assert json.loads(json.dumps(d)) == d


def test_sparse_doc_omits_empty_sections():
    doc = _load("valid_aggregates_only.json")
    d = to_braket_standardized(doc)
    # aggregates-only -> no per-qubit / two-qubit data
    assert "oneQubitProperties" not in d
    assert "twoQubitProperties" not in d
    assert d["braketSchemaHeader"]["version"] == "1"


def test_registered_in_registry():
    from oq_cal import registry

    assert "braket" in registry.list_formats()["exporters"]


def test_unlabeled_error_and_process_fidelity_are_not_invented_as_rb():
    doc = OqCalDocument(
        oq_cal=Header(version="0.1"),
        device=Device(id="synthetic", num_qubits=2),
        snapshot=Snapshot(source="synthetic"),
        gates=[
            GateEntry(
                name="cz",
                qubits=["$0", "$1"],
                error=Datum(value=0.01, unit=Unit.DIMENSIONLESS),
            ),
            GateEntry(
                name="cx",
                qubits=["$0", "$1"],
                fidelity=Datum(value=0.99, unit=Unit.DIMENSIONLESS, metric="process_fidelity"),
            ),
            GateEntry(
                name="x",
                qubits=["$0", "$1"],
                error=Datum(
                    value=0.004,
                    unit=Unit.DIMENSIONLESS,
                    method="rb",
                    metric="average_gate_error",
                ),
            ),
        ],
        qubits={
            "$0": QubitProperties(
                readout=Readout(
                    fidelity=Datum(value=0.95, unit=Unit.DIMENSIONLESS, method="rb")
                )
            )
        },
    )
    exported = to_braket_standardized(doc)
    assert "twoQubitProperties" in exported
    names = {
        (item["gateName"], item["fidelityType"]["name"])
        for item in exported["twoQubitProperties"]["0-1"]["twoQubitGateFidelity"]
    }
    assert names == {("X", "RANDOMIZED_BENCHMARKING")}
    readout = exported["oneQubitProperties"]["0"]["oneQubitFidelity"]
    assert readout[0]["fidelityType"]["name"] == "RANDOMIZED_BENCHMARKING"
    assert readout[0]["fidelity"] == pytest.approx(0.95)


def test_rigetti_source_exports_capabilities_without_inventing_ports():
    payload = json.loads(
        (
            Path(__file__).resolve().parents[2]
            / "fixtures"
            / "sources"
            / "rigetti"
            / "synthetic_rigetti_capabilities.json"
        ).read_text()
    )
    doc = from_braket(payload)
    exported = to_braket(doc)
    assert exported["braketSchemaHeader"]["name"].endswith("rigetti_device_capabilities")
    assert exported["braketSchemaHeader"]["version"] == "2"
    assert exported["paradigm"]["qubitCount"] == 3
    assert "nativeGateSet" not in exported["paradigm"]
    assert exported["paradigm"]["connectivity"]["connectivityGraph"]["0"] == ["1"]
    assert "ports" not in exported.get("pulse", {})
    frame = exported["pulse"]["frames"]["rx_q0"]
    assert frame["frequency"] == pytest.approx(4500000000)
    assert frame["associatedGate"] == "rx"
    assert frame["qubitMappings"] == [0]
    fid = exported["standardized"]["oneQubitProperties"]["0"]["oneQubitFidelity"][0]
    assert fid["fidelityType"]["name"] == "READOUT"
    assert fid["fidelity"] == pytest.approx(0.97)

    again = from_braket(exported)
    assert again.device.coupling_map == doc.device.coupling_map
    assert again.defcals[0].params["frequency_hz"] == pytest.approx(4500000000)
    assert again.qubits["$0"].readout.fidelity.metric == "readout_fidelity"
    assert again.qubits["$0"].t1.value == pytest.approx(doc.qubits["$0"].t1.value)
