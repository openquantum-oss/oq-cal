"""Tests for the Braket standardized-properties importer."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from oq_cal.importers.braket import BraketSchemaError, from_braket_standardized
from oq_cal.models import OqCalDocument
from oq_cal.validate import validate

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "sources" / "braket"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


# num_qubits overrides for aggregates-only payloads that cannot infer it.
_NQ = {
    "raw_ionq-forte-1.json": 36,
    "raw_ionq-forte-1-enterprise.json": 36,
}


def _import(name: str) -> OqCalDocument:
    kwargs = {}
    if name in _NQ:
        kwargs["num_qubits"] = _NQ[name]
    return from_braket_standardized(_load(name), **kwargs)


@pytest.mark.parametrize(
    "name",
    [
        "braket_standardized_cepheus_108.json",
        "raw_iqm-garnet.json",
        "raw_iqm-emerald.json",
        "raw_aqt-ibex-q1.json",
        "raw_ionq-forte-1.json",
        "raw_ionq-forte-1-enterprise.json",
    ],
)
def test_fixture_imports_and_validates(name):
    doc = _import(name)
    issues = validate(doc)
    assert issues == [], f"{name}: {[str(i) for i in issues]}"


def test_all_braket_fixtures_via_conftest(braket_file):
    """Every braket fixture the conftest parametrizes imports clean."""
    payload = json.loads(braket_file.read_text())
    kwargs = {}
    # aggregates-only v3 payloads need an explicit count
    if not payload.get("oneQubitProperties") and not payload.get("twoQubitProperties"):
        kwargs["num_qubits"] = 36
    doc = from_braket_standardized(payload, **kwargs)
    assert validate(doc) == []


def test_unknown_schema_name_raises():
    with pytest.raises(BraketSchemaError):
        from_braket_standardized({"braketSchemaHeader": {"name": "nope", "version": "1"}})


def test_unknown_version_raises():
    hdr = {
        "braketSchemaHeader": {
            "name": "braket.device_schema.standardized_gate_model_qpu_device_properties",
            "version": "2",
        }
    }
    with pytest.raises(BraketSchemaError):
        from_braket_standardized(hdr)


def test_aggregates_only_without_num_qubits_emits_doc():
    """Aggregates-only payloads no longer raise: num_qubits is simply absent
    (spec §4), the doc validates clean, and the caller override still works."""
    payload = _load("raw_ionq-forte-1.json")
    doc = from_braket_standardized(payload)  # no num_qubits
    assert doc.device.num_qubits is None
    assert doc.qubits is None  # aggregates-only
    assert doc.aggregates is not None
    assert validate(doc) == []
    # the explicit caller override is still honoured
    doc2 = from_braket_standardized(payload, num_qubits=36)
    assert doc2.device.num_qubits == 36
    assert validate(doc2) == []


# --- spot-value assertions -------------------------------------------------


def test_cepheus_v1_qubit0_t1_and_num_qubits():
    doc = _import("braket_standardized_cepheus_108.json")
    assert doc.snapshot.source_schema.endswith("v1")
    t1 = doc.qubits["$0"].t1
    assert t1.unit == "s"
    assert t1.value == pytest.approx(3.222084378240453e-05)
    # keys 0..107 -> num_qubits 108
    assert doc.device.num_qubits == 108


def test_garnet_qubit0_t1_si_from_capital_S():
    # IQM Garnet is a 1-based source: source key "1" is remapped to $0.
    doc = _import("raw_iqm-garnet.json")
    t1 = doc.qubits["$0"].t1
    assert t1.unit == "s"
    assert t1.value == pytest.approx(2.6136884458246837e-05)
    assert t1.std_error == pytest.approx(1.1410913829427858e-06)


def test_garnet_one_based_remapped_to_zero_based():
    """Garnet uses 1-based source keys ("1".."20"); remap to dense 0-based $0..$19."""
    doc = _import("raw_iqm-garnet.json")
    assert doc.device.num_qubits == 20
    assert set(doc.qubits.keys()) == {f"${i}" for i in range(20)}
    assert "$20" not in doc.qubits  # no phantom top qubit
    # qubit_labels bridges 0-based $n back to vendor numbering.
    labels = doc.device.qubit_labels
    assert labels is not None
    assert labels["$0"] == "1"
    assert labels["$19"] == "20"
    assert len(labels) == 20


def test_cepheus_zero_based_kept_verbatim_with_gap():
    """Cepheus is already 0-based (key "0" present): no shift, no labels, gaps kept."""
    doc = _import("braket_standardized_cepheus_108.json")
    assert doc.device.num_qubits == 108
    assert doc.device.qubit_labels is None  # no shift -> no labels from this mechanism
    # source is sparse (key "8" absent); it stays sparse, we do NOT densify.
    assert "$8" not in doc.qubits
    assert "$0" in doc.qubits and "$107" in doc.qubits


def test_emerald_confusion_matrix_from_readout_errors():
    # Emerald is 1-based: source key "1" (e01=0.002, e10=0.0074) remaps to $0.
    doc = _import("raw_iqm-emerald.json")
    cm = doc.qubits["$0"].readout.confusion_matrix
    assert cm[0] == pytest.approx([0.998, 0.002])
    assert cm[1] == pytest.approx([0.0074, 0.9926])
    # rows sum ~1
    for row in cm:
        assert sum(row) == pytest.approx(1.0)
    # READOUT fidelity preserved alongside
    assert doc.qubits["$0"].readout.fidelity.value == pytest.approx(0.9953)
    # 1-based source -> shift applied -> labels recorded; still 54 qubits.
    assert doc.device.num_qubits == 54
    assert doc.device.qubit_labels["$0"] == "1"


def test_two_qubit_clifford_is_benchmark_not_gate():
    doc = _import("raw_iqm-emerald.json")
    gate_names = {g.name for g in doc.gates}
    assert "Two_Qubit_Clifford" not in gate_names
    assert "two_qubit_clifford" not in gate_names
    # It appears as a benchmark on the CZ pair entry (source pair "1-2" -> ["$0","$1"]).
    cz = next(g for g in doc.gates if g.name == "cz" and g.qubits == ["$0", "$1"])
    protocols = {b.protocol for b in (cz.benchmarks or [])}
    assert "two_qubit_clifford" in protocols
    # cz gate itself keeps a fidelity datum
    assert cz.fidelity is not None


def test_aqt_mixed_granularity_units_and_median():
    doc = _import("raw_aqt-ibex-q1.json")
    # readoutDuration 1000 us -> 1e-3 s
    assert doc.aggregates.readout.duration.value == pytest.approx(1e-3)
    assert doc.aggregates.readout.duration.unit == "s"
    # single-qubit gate duration 45 us -> 4.5e-5 s
    assert doc.aggregates.gates_1q.duration.value == pytest.approx(45e-6)
    # per-qubit RB fidelity present, "fraction" dropped to dimensionless
    rb = doc.qubits["$0"].benchmarks[0]
    assert rb.protocol == "rb"
    assert rb.fidelity.unit == "dimensionless"
    assert rb.fidelity.value == pytest.approx(0.9997)
    assert rb.fidelity.metric is None
    # singleQubitFidelity median passes through
    assert doc.aggregates.gates_1q.fidelity.median == pytest.approx(0.9998)
    # Untyped readoutFidelity: the field name is the only quantity signal.
    assert doc.aggregates.readout.fidelity.method is None
    assert doc.aggregates.readout.fidelity.metric == "readout_fidelity"


def test_ionq_aggregates_only_and_std_error_zero_dropped():
    doc = _import("raw_ionq-forte-1.json")
    assert doc.device.num_qubits == 36  # caller override
    assert doc.qubits is None  # aggregates-only
    # standardError: 0 in source -> omitted
    assert doc.aggregates.gates_1q.fidelity.std_error is None
    assert doc.aggregates.gates_2q.fidelity.std_error is None
    # activeResetDuration -> ops.reset_duration
    assert doc.aggregates.ops["reset_duration"].value == pytest.approx(5e-5)
    # updatedAt -> captured_at
    assert doc.snapshot.captured_at == "2026-10-30T00:00:00+00:00"
    # long fidelityType.description not stuffed into method.
    # IonQ types readoutFidelity as randomized benchmarking, so the protocol
    # is method and the quantity is not labeled readout_fidelity.
    assert doc.aggregates.readout.fidelity.method == "rb"
    assert doc.aggregates.readout.fidelity.metric is None
    assert doc.aggregates.gates_1q.fidelity.metric is None


def test_garnet_coupling_map_directed_both_directions():
    """30 undirected twoQubitProperties pairs -> 60 directed coupling_map pairs."""
    doc = _import("raw_iqm-garnet.json")
    cm = doc.device.coupling_map
    assert cm is not None
    assert len(cm) == 60
    # sorted numerically by (i, j); every pair is $-prefixed
    nums = [(int(a[1:]), int(b[1:])) for a, b in cm]
    assert nums == sorted(nums)
    # both directions present and symmetric
    s = {(a, b) for a, b in nums}
    assert all((b, a) in s for (a, b) in s)
    assert len(s) == 60  # no duplicates
    # all refs in range
    assert all(0 <= n < doc.device.num_qubits for pair in nums for n in pair)
    assert validate(doc) == []


def test_cepheus_coupling_map_193_to_386():
    doc = _import("braket_standardized_cepheus_108.json")
    cm = doc.device.coupling_map
    assert cm is not None and len(cm) == 386


def test_emerald_coupling_map_87_to_174():
    doc = _import("raw_iqm-emerald.json")
    assert len(doc.device.coupling_map) == 174


def test_aggregates_only_no_coupling_map():
    """v3 aggregates-only payloads carry no pair evidence -> no coupling_map."""
    for name in ("raw_aqt-ibex-q1.json", "raw_ionq-forte-1.json"):
        doc = _import(name)
        assert doc.device.coupling_map is None, name


def test_extensions_preserve_full_payload_verbatim():
    payload = _load("raw_iqm-garnet.json")
    doc = from_braket_standardized(payload)
    assert doc.extensions["braket"] == payload


def test_round_trip_json():
    doc = _import("raw_iqm-emerald.json")
    reparsed = OqCalDocument.model_validate_json(doc.model_dump_json())
    assert reparsed.device.num_qubits == doc.device.num_qubits
    assert validate(reparsed) == []


# ---------------------------------------------------------------------------
# Convert-time identity / provenance overrides (feedback 001 + 002)
# ---------------------------------------------------------------------------


def test_identity_kwargs_override_source_and_default():
    doc = from_braket_standardized(
        _load("raw_iqm-garnet.json"),
        device_id="aws:iqm.garnet",
        vendor="IQM",
        model="Garnet",
        captured_at="2026-10-31T00:00:00+00:00",
        snapshot_id="demo-0001",
    )
    assert doc.device.id == "aws:iqm.garnet"
    assert doc.device.vendor == "IQM"
    assert doc.device.model == "Garnet"
    assert doc.snapshot.captured_at == "2026-10-31T00:00:00+00:00"
    assert doc.snapshot.id == "demo-0001"


def test_device_id_falls_back_to_constant_when_omitted():
    doc = from_braket_standardized(_load("raw_iqm-garnet.json"))
    assert doc.device.id == "braket-device"


# ---------------------------------------------------------------------------
# Dead-element sentinel (feedback 003)
# ---------------------------------------------------------------------------


def _unmeasured_qubits(doc: OqCalDocument) -> set[str]:
    out: set[str] = set()
    for ref, qp in (doc.qubits or {}).items():
        datums = [qp.t1, qp.t2, qp.t2_echo]
        if qp.readout is not None:
            datums.append(qp.readout.fidelity)
        for bm in qp.benchmarks or []:
            datums.append(bm.fidelity)
        if any(d is not None and d.status == "unmeasured" for d in datums):
            out.add(ref)
    return out


def _unmeasured_gate_entries(doc: OqCalDocument) -> int:
    n = 0
    for g in doc.gates or []:
        if (g.fidelity is not None and g.fidelity.status == "unmeasured") or (
            g.error is not None and g.error.status == "unmeasured"
        ):
            n += 1
    return n


def test_cepheus_sentinel_counts():
    """The real Cepheus-108 payload carries exactly 4 sentinel qubits and 29
    sentinel CZ edges, all flagged status 'unmeasured'."""
    doc = from_braket_standardized(_load("braket_standardized_cepheus_108.json"))
    assert _unmeasured_qubits(doc) == {"$19", "$37", "$41", "$76"}
    assert _unmeasured_gate_entries(doc) == 29


def test_sentinel_datum_drops_std_error_keeps_value():
    doc = from_braket_standardized(_load("braket_standardized_cepheus_108.json"))
    qp = doc.qubits["$19"]
    # the RB benchmark on a dead qubit is the sentinel datum
    sentinel = next(
        b.fidelity for b in qp.benchmarks if b.fidelity.status == "unmeasured"
    )
    assert sentinel.value == 0.5
    assert sentinel.std_error is None


def test_no_false_positive_sentinels_on_live_devices():
    """Garnet and Emerald import with zero unmeasured datums."""
    for name in ("raw_iqm-garnet.json", "raw_iqm-emerald.json"):
        doc = from_braket_standardized(_load(name))
        assert _unmeasured_qubits(doc) == set(), name
        assert _unmeasured_gate_entries(doc) == 0, name
