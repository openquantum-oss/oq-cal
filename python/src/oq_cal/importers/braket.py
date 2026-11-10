"""Importer for AWS Braket standardized gate-model QPU device properties.

Handles ``braket.device_schema.standardized_gate_model_qpu_device_properties``
schema versions 1 and 3, which share a name but differ substantially in shape:

* **v1** (e.g. IQM Garnet/Emerald/Cepheus) carries only per-qubit
  ``oneQubitProperties`` and per-pair ``twoQubitProperties``.
* **v3** (e.g. AQT, IonQ) adds device-level aggregates (``T1``, ``T2``,
  ``readoutFidelity``, gate durations/fidelities, ...). Some v3 payloads are
  aggregates-only (trapped-ion, all-to-all) and carry no per-qubit data at all.

All source units are normalized to base SI (``"S"``/``"s"`` -> ``s``, ``us``
-> ``s`` with a 1e-6 factor, ``"fraction"`` -> ``dimensionless``). The complete
source payload is preserved verbatim under ``extensions["braket"]`` so that the
conversion is never lossy.
"""

from __future__ import annotations

from typing import Any, Optional

from ..models import (
    Aggregates,
    Benchmark,
    Datum,
    Device,
    GateEntry,
    Header,
    OqCalDocument,
    QubitProperties,
    Readout,
    Snapshot,
    _AggGate,
    _AggQubits,
    _AggReadout,
)
from ..registry import register_importer
from ._identity import Identity, apply_identity

SCHEMA_NAME = "braket.device_schema.standardized_gate_model_qpu_device_properties"

# fidelityType.name -> short snake_case method / benchmark-protocol id.
_FIDELITY_METHOD = {
    "RANDOMIZED_BENCHMARKING": "rb",
    "SIMULTANEOUS_RANDOMIZED_BENCHMARKING": "simultaneous_rb",
    "INTERLEAVED_RANDOMIZED_BENCHMARKING": "interleaved_rb",
    "SIMULTANEOUS_INTERLEAVED_RANDOMIZED_BENCHMARKING": "simultaneous_interleaved_rb",
    "READOUT": "readout",
}

# gateName -> stdgates vocabulary where a standard name exists.
_GATE_NAME = {
    "cz": "cz",
    "cx": "cx",
    "cnot": "cx",
    "x": "x",
    "y": "y",
    "z": "z",
    "h": "h",
    "s": "s",
    "sx": "sx",
    "rx": "rx",
    "ry": "ry",
    "rz": "rz",
    "swap": "swap",
    "ccx": "ccx",
    "x90": "sx",
    "cphase": "cz",
}

# gateName values that are protocol benchmarks, not physical gates.
_BENCHMARK_GATE_NAMES = {"two_qubit_clifford", "one_qubit_clifford", "clifford"}


class BraketSchemaError(ValueError):
    """Raised for an unrecognised Braket standardized-properties schema."""


# ---------------------------------------------------------------------------
# Unit / datum helpers
# ---------------------------------------------------------------------------


def _to_seconds(value: float, unit: Optional[str]) -> tuple[float, str]:
    u = (unit or "").lower()
    if u in ("s", ""):  # "S" / "s" / missing -> seconds
        return value, "s"
    if u in ("us", "µs", "microsecond", "microseconds"):
        return value * 1e-6, "s"
    if u in ("ms", "millisecond", "milliseconds"):
        return value * 1e-3, "s"
    if u in ("ns", "nanosecond", "nanoseconds"):
        return value * 1e-9, "s"
    # Unknown time unit: pass the value through, best-effort SI label.
    return value, "s"


def _time_datum(entry: dict, **extra: Any) -> Datum:
    """Build a seconds Datum from a Braket ``{value, unit, standardError}`` block."""
    value, _ = _to_seconds(float(entry["value"]), entry.get("unit"))
    kw: dict[str, Any] = {"value": value, "unit": "s"}
    se = entry.get("standardError")
    if se:  # drop 0 / None: source 0 means "not reported"
        # scale std error by the same factor as the value
        factor = value / float(entry["value"]) if entry["value"] else 1.0
        kw["std_error"] = se * factor
    kw.update(extra)
    return Datum(**kw)


def _is_sentinel(entry: dict) -> bool:
    """Detect Braket's uncalibrated-element sentinel.

    Braket marks a dead / uncalibrated qubit or edge with the exact numeric pair
    ``fidelity == 0.5`` AND ``standardError == 1`` on the parsed JSON numbers.
    """
    return entry.get("fidelity") == 0.5 and entry.get("standardError") == 1


def _fidelity_datum(entry: dict, *, metric: Optional[str] = None) -> Datum:
    """Build a dimensionless fidelity/error Datum from a fidelity-list entry.

    ``unit: "fraction"`` is dropped (treated as dimensionless). ``median`` passes
    through. ``standardError: 0`` is omitted. The fidelityType name maps to a
    short ``method`` id; the (possibly long) ``description`` is *not* stuffed into
    ``method`` -- it survives verbatim in ``extensions``.

    ``metric`` is set only when the source names the quantity. ``READOUT`` is a
    readout fidelity. Randomized benchmarking names a protocol, not whether the
    number is an average gate fidelity, a process fidelity, or a decay parameter,
    so those entries keep ``method`` and leave ``metric`` unset.

    A sentinel datum (see :func:`_is_sentinel`) keeps ``value: 0.5`` but DROPS
    the std_error (it is a marker, not a measurement) and is flagged
    ``status: "unmeasured"`` so downstream consumers exclude it from aggregates.
    """
    kw: dict[str, Any] = {"value": float(entry["fidelity"]), "unit": "dimensionless"}
    if metric:
        kw["metric"] = metric
    if _is_sentinel(entry):
        kw["status"] = "unmeasured"
        if entry.get("median") is not None:
            kw["median"] = entry["median"]
        ftype = entry.get("fidelityType") or {}
        name = ftype.get("name")
        if name:
            method = _FIDELITY_METHOD.get(name)
            if method:
                kw["method"] = method
        return Datum(**kw)
    se = entry.get("standardError")
    if se:
        kw["std_error"] = se
    if entry.get("median") is not None:
        kw["median"] = entry["median"]
    ftype = entry.get("fidelityType") or {}
    name = ftype.get("name")
    if name:
        method = _FIDELITY_METHOD.get(name)
        if method:
            kw["method"] = method
    return Datum(**kw)


# ---------------------------------------------------------------------------
# Per-qubit (v1 + mixed v3)
# ---------------------------------------------------------------------------


def _build_qubit(props: dict) -> QubitProperties:
    qp = QubitProperties()
    if "T1" in props:
        qp.t1 = _time_datum(props["T1"])
    if "T2" in props:
        qp.t2 = _time_datum(props["T2"])

    readout = Readout()
    benchmarks: list[Benchmark] = []
    e01: Optional[float] = None
    e10: Optional[float] = None

    for entry in props.get("oneQubitFidelity", []) or []:
        ftype = (entry.get("fidelityType") or {}).get("name")
        if ftype == "READOUT":
            readout.fidelity = _fidelity_datum(entry, metric="readout_fidelity")
        elif ftype == "READOUT_ERROR_0_TO_1":
            e01 = float(entry["fidelity"])
        elif ftype == "READOUT_ERROR_1_TO_0":
            e10 = float(entry["fidelity"])
        else:
            # Everything else (RB, simultaneous RB, ...) is a 1q benchmark.
            benchmarks.append(_benchmark_from_entry(entry, qubits=None))

    if e01 is not None or e10 is not None:
        a = e01 or 0.0
        b = e10 or 0.0
        # Row i = probabilities of assigning each outcome given prepared state i.
        readout.confusion_matrix = [[1.0 - a, a], [b, 1.0 - b]]

    if readout.model_dump(exclude_none=True):
        qp.readout = readout
    if benchmarks:
        qp.benchmarks = benchmarks
    return qp


def _benchmark_from_entry(entry: dict, qubits: Optional[list[str]]) -> Benchmark:
    ftype = (entry.get("fidelityType") or {}).get("name")
    protocol = _FIDELITY_METHOD.get(ftype, (ftype or "benchmark").lower())
    bm = Benchmark(protocol=protocol)
    bm.fidelity = _fidelity_datum(entry)
    if qubits:
        bm.qubits = qubits
    return bm


# ---------------------------------------------------------------------------
# Per-pair (v1)
# ---------------------------------------------------------------------------


def _pair_qubits(key: str, shift: int) -> list[str]:
    parts = key.split("-")
    return [f"${int(p) - shift}" for p in parts]


def _coupling_map(pairs: set[tuple[int, int]]) -> list[list[str]]:
    """Emit DIRECTED coupling-map pairs from undirected qubit pairs.

    Each undirected ``(i, j)`` emits both directions; the full directed list is
    sorted numerically by ``(i, j)``.
    """
    directed: set[tuple[int, int]] = set()
    for i, j in pairs:
        directed.add((i, j))
        directed.add((j, i))
    return [[f"${i}", f"${j}"] for i, j in sorted(directed)]


def _build_pair_gates(key: str, props: dict, shift: int) -> list[GateEntry]:
    qubits = _pair_qubits(key, shift)
    gates: list[GateEntry] = []
    benchmarks: list[Benchmark] = []
    for entry in props.get("twoQubitGateFidelity", []) or []:
        raw_name = entry.get("gateName", "")
        norm = raw_name.lower()
        if norm in _BENCHMARK_GATE_NAMES:
            # Protocol aggregate -> a benchmark on the pair, never a gate name.
            bm = _benchmark_from_entry(entry, qubits=qubits)
            bm.protocol = norm  # keep the protocol identity (e.g. two_qubit_clifford)
            benchmarks.append(bm)
            continue
        name = _GATE_NAME.get(norm, norm)
        ge = GateEntry(name=name, qubits=qubits)
        ge.fidelity = _fidelity_datum(entry)
        gates.append(ge)
    if benchmarks:
        if gates:
            # Attach benchmarks to the first gate entry on the pair.
            gates[0].benchmarks = benchmarks
        else:
            # No concrete gate: emit a benchmarks-only gate entry (no fidelity).
            gates.append(GateEntry(name="benchmark", qubits=qubits, benchmarks=benchmarks))
    return gates


# ---------------------------------------------------------------------------
# Aggregates (v3)
# ---------------------------------------------------------------------------


def _first_fidelity(entries: Optional[list], *, metric: Optional[str] = None) -> Optional[Datum]:
    if not entries:
        return None
    return _fidelity_datum(entries[0], metric=metric)


def _readout_aggregate_metric(entries: Optional[list]) -> Optional[str]:
    """Metric for one device-level ``readoutFidelity`` item.

    The field name is a readout fidelity only when the entry does not name a
    different protocol. An absent ``fidelityType`` (AQT) or ``READOUT`` names
    the quantity. IonQ types the same field ``RANDOMIZED_BENCHMARKING``, which
    is a protocol, so ``metric`` stays unset and ``method`` stays ``rb``.
    """
    if not entries:
        return None
    ftype = (entries[0].get("fidelityType") or {}).get("name")
    if ftype in (None, "READOUT"):
        return "readout_fidelity"
    return None


def _build_aggregates(payload: dict) -> Optional[Aggregates]:
    agg = Aggregates()

    aq = _AggQubits()
    if "T1" in payload:
        aq.t1 = _time_datum(payload["T1"])
    if "T2" in payload:
        aq.t2 = _time_datum(payload["T2"])
    if aq.model_dump(exclude_none=True):
        agg.qubits = aq

    ar = _AggReadout()
    readout_entries = payload.get("readoutFidelity")
    rf = _first_fidelity(readout_entries, metric=_readout_aggregate_metric(readout_entries))
    if rf is not None:
        ar.fidelity = rf
    if "readoutDuration" in payload:
        ar.duration = _time_datum(payload["readoutDuration"])
    if ar.model_dump(exclude_none=True):
        agg.readout = ar

    g1 = _AggGate()
    f1 = _first_fidelity(payload.get("singleQubitFidelity"))
    if f1 is not None:
        g1.fidelity = f1
    if "singleQubitGateDuration" in payload:
        g1.duration = _time_datum(payload["singleQubitGateDuration"])
    if g1.model_dump(exclude_none=True):
        agg.gates_1q = g1

    g2 = _AggGate()
    f2 = _first_fidelity(payload.get("twoQubitGateFidelity"))
    if f2 is not None:
        g2.fidelity = f2
    if "twoQubitGateDuration" in payload:
        g2.duration = _time_datum(payload["twoQubitGateDuration"])
    if g2.model_dump(exclude_none=True):
        agg.gates_2q = g2

    if "activeResetDuration" in payload:
        agg.ops = {"reset_duration": _time_datum(payload["activeResetDuration"])}

    if agg.model_dump(exclude_none=True):
        return agg
    return None


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def from_braket_standardized(
    payload: dict,
    *,
    device_id: Optional[str] = None,
    vendor: Optional[str] = None,
    model: Optional[str] = None,
    captured_at: Optional[str] = None,
    snapshot_id: Optional[str] = None,
    num_qubits: Optional[int] = None,
) -> OqCalDocument:
    """Convert a Braket standardized-properties payload to a :class:`OqCalDocument`.

    Parameters
    ----------
    payload:
        The raw ``standardized_gate_model_qpu_device_properties`` dict.
    device_id, vendor, model, captured_at, snapshot_id:
        Optional device identity / capture provenance. A supplied value
        OVERRIDES whatever the importer would derive from the source; omitting it
        leaves the source-derived (or absent) behavior. The Braket source payload
        carries no device identity, so ``device_id`` falls back to the constant
        ``"braket-device"`` only when neither this argument nor the source supply
        one.
    num_qubits:
        Optional caller override for the qubit count. For payloads carrying
        ``oneQubitProperties``/``twoQubitProperties`` the count is inferred
        (max index + 1) and this argument, if given, is used as a floor. For
        aggregates-only v3 payloads (e.g. IonQ) the count cannot be inferred:
        pass ``num_qubits=`` to set it, or omit it and the emitted document will
        carry no ``device.num_qubits`` (valid per spec §4; consumers treat the
        qubit count as unknown).
    """
    header = payload.get("braketSchemaHeader") or {}
    if header.get("name") != SCHEMA_NAME:
        raise BraketSchemaError(
            f"unsupported Braket schema {header.get('name')!r}; "
            f"expected {SCHEMA_NAME!r}"
        )
    version = str(header.get("version", ""))
    if version not in ("1", "3"):
        raise BraketSchemaError(
            f"unsupported {SCHEMA_NAME} version {version!r}; supported: 1, 3"
        )

    one_qubit = payload.get("oneQubitProperties") or {}
    two_qubit = payload.get("twoQubitProperties") or {}

    # 1-based detection. oq-cal $n indices are ALWAYS 0-based (spec §4). Some
    # vendors (notably IQM on Braket) number qubits from 1. Collect every source
    # index that appears in oneQubitProperties keys and twoQubitProperties pair
    # keys: if index 0 appears nowhere AND index 1 appears, the source is 1-based
    # and every index is shifted down by 1. Otherwise indices are kept verbatim,
    # INCLUDING gaps (an already-0-based sparse payload stays sparse; we never
    # densify).
    source_indices: set[int] = set()
    for key in one_qubit:
        source_indices.add(int(key))
    for key in two_qubit:
        for p in key.split("-"):
            source_indices.add(int(p))
    shift = 1 if (0 not in source_indices and 1 in source_indices) else 0

    qubits: dict[str, QubitProperties] = {}
    for key, props in one_qubit.items():
        qp = _build_qubit(props)
        if qp.model_dump(exclude_none=True):
            qubits[f"${int(key) - shift}"] = qp

    gates: list[GateEntry] = []
    pair_evidence: set[tuple[int, int]] = set()
    for key, props in two_qubit.items():
        gates.extend(_build_pair_gates(key, props, shift))
        parts = key.split("-")
        if len(parts) == 2:
            # Braket v1 pair keys are undirected (IQM CZ is bidirectional).
            pair_evidence.add((int(parts[0]) - shift, int(parts[1]) - shift))

    aggregates = _build_aggregates(payload)

    # num_qubits: infer from qubit/pair indices; fall back to the caller argument;
    # otherwise leave unset. Aggregates-only payloads (e.g. IonQ, all-to-all) carry
    # no per-qubit index to infer from and publish no count, so num_qubits is simply
    # absent; the spec allows this (§4) and consumers treat the count as unknown.
    inferred: Optional[int] = None
    if source_indices:
        inferred = (max(source_indices) - shift) + 1
    if inferred is not None and num_qubits is not None:
        nq: Optional[int] = max(inferred, num_qubits)
    elif inferred is not None:
        nq = inferred
    elif num_qubits is not None:
        nq = num_qubits
    else:
        nq = None

    snapshot = Snapshot(source="aws-braket", source_schema=f"{SCHEMA_NAME} v{version}")
    if payload.get("updatedAt"):
        snapshot.captured_at = payload["updatedAt"]

    # Braket payloads carry no device identity: "braket-device" is a last-resort
    # fallback, used only when neither the caller nor the source supplies an id.
    device = Device(id="braket-device", num_qubits=nq)
    if shift:
        # A shift was applied: record the original vendor numbering so the bridge
        # from 0-based $n back to the source keys is never lost ("$0" -> "1", ...).
        device.qubit_labels = {
            f"${idx - shift}": str(idx) for idx in sorted(source_indices)
        }
    if pair_evidence:
        device.coupling_map = _coupling_map(pair_evidence)

    apply_identity(
        device,
        snapshot,
        Identity(
            device_id=device_id,
            vendor=vendor,
            model=model,
            captured_at=captured_at,
            snapshot_id=snapshot_id,
        ),
    )

    doc = OqCalDocument(
        oq_cal=Header(version="0.1"),
        device=device,
        snapshot=snapshot,
        extensions={"braket": payload},
    )
    if aggregates is not None:
        doc.aggregates = aggregates
    if qubits:
        doc.qubits = qubits
    if gates:
        doc.gates = gates
    return doc


def from_braket(
    payload: dict,
    *,
    device_id: Optional[str] = None,
    vendor: Optional[str] = None,
    model: Optional[str] = None,
    captured_at: Optional[str] = None,
    snapshot_id: Optional[str] = None,
    num_qubits: Optional[int] = None,
) -> OqCalDocument:
    """Convert an AWS Braket device document to a :class:`OqCalDocument`.

    Dispatches on ``braketSchemaHeader.name``. Standardized gate-model
    properties (versions 1 and 3) and Rigetti device capabilities (version 2)
    are both accepted. The schema-specific functions remain available when the
    caller already knows which document it holds.
    """
    # Imported lazily: rigetti.py imports the standardized converter from here.
    from .rigetti import RIGETTI_SCHEMA, from_braket_rigetti

    header = payload.get("braketSchemaHeader") or {}
    name = header.get("name")
    kwargs = dict(
        device_id=device_id,
        vendor=vendor,
        model=model,
        captured_at=captured_at,
        snapshot_id=snapshot_id,
        num_qubits=num_qubits,
    )
    if name == SCHEMA_NAME:
        return from_braket_standardized(payload, **kwargs)
    if name == RIGETTI_SCHEMA:
        return from_braket_rigetti(payload, **kwargs)
    raise BraketSchemaError(
        f"unsupported Braket schema {name!r}; "
        f"expected {SCHEMA_NAME!r} or {RIGETTI_SCHEMA!r}"
    )


register_importer("braket", from_braket)
