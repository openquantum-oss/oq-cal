"""Export an oq-cal document to an AWS Braket device dict.

``to_braket`` is the registered exporter. A document whose
``snapshot.source_schema`` names Rigetti device capabilities is written as that
schema, version 2. Every other document is written as standardized gate-model
properties, version 1. Neither shape depends on the Braket SDK.

The standardized structure is::

    {
      "braketSchemaHeader": {
        "name": "braket.device_schema.standardized_gate_model_qpu_device_properties",
        "version": "1"
      },
      "oneQubitProperties": { "<n>": { "T1": {...}, "T2": {...},
                                       "oneQubitFidelity": [ ... ] }, ... },
      "twoQubitProperties": { "<i>-<j>": { "twoQubitGateFidelity": [ ... ] }, ... }
    }

Mapping notes
-------------
* **Coherence.** ``T1``/``T2`` are emitted as ``{value, standardError?, unit: "S"}``.
  Braket's standardized schema uses ``"S"`` for seconds; oq-cal stores base SI
  seconds, so values pass through unchanged and only the unit *string* differs.
* **One-qubit fidelity.** A known ``method`` or benchmark ``protocol`` maps to a
  ``fidelityType.name`` (``rb`` -> ``RANDOMIZED_BENCHMARKING``, ``readout`` ->
  ``READOUT``). ``metric: readout_fidelity`` with no protocol is ``READOUT``.
  An untyped number on ``readout.fidelity`` is ``READOUT`` because the field is
  the only signal. A protocol of ``rb`` on that field stays randomized
  benchmarking. No fidelity type is invented when neither the method nor the
  metric names one. Confusion-matrix off-diagonals, when present, are
  additionally emitted as directional readout-error entries
  (``READOUT_ERROR_0_TO_1`` = P(1|0), ``READOUT_ERROR_1_TO_0`` = P(0|1)).
* **Two-qubit fidelity.** Built from two-qubit ``gates`` entries. ``gateName`` is
  the uppercased gate name. An ``error`` datum becomes ``1 - error`` only when
  its ``metric`` is ``average_gate_error`` and its ``method`` names a Braket
  fidelity type. An unlabeled error is left as an error.
* **Rigetti capabilities.** Qubit count, the directed coupling map, pulse-frame
  frequencies from defcals, and a nested standardized block when the document
  has per-qubit or per-pair data. Ports, the native-gate list, and other
  extension residue are not reconstructed.
* **Unmappable residue.** Anything that does not fit the chosen schema
  (aggregates, anharmonicity, classifiers, native-only gate params, …) is
  omitted. On an oq-cal document it still lives under ``extensions``.
"""

from __future__ import annotations

from typing import Any, Optional

from ..models import OqCalDocument
from ..registry import register_exporter

_SCHEMA_NAME = "braket.device_schema.standardized_gate_model_qpu_device_properties"
_SCHEMA_VERSION = "1"
_RIGETTI_SCHEMA = "braket.device_schema.rigetti.rigetti_device_capabilities"
_PARADIGM_SCHEMA = "braket.device_schema.gate_model_qpu_paradigm_properties"

# oq-cal method / protocol id -> Braket fidelityType.name.
# Absent from this map means the protocol is not a Braket fidelity type.
_FIDELITY_TYPE = {
    "rb": "RANDOMIZED_BENCHMARKING",
    "randomized_benchmarking": "RANDOMIZED_BENCHMARKING",
    "simultaneous_rb": "SIMULTANEOUS_RANDOMIZED_BENCHMARKING",
    "interleaved_rb": "INTERLEAVED_RANDOMIZED_BENCHMARKING",
    "direct_rb": "RANDOMIZED_BENCHMARKING",
    "readout": "READOUT",
}

# Metrics that are not a readout fidelity and must not be labeled READOUT
# just because the datum sits on a readout field.
_NOT_READOUT = frozenset(
    {
        "average_gate_fidelity",
        "process_fidelity",
        "state_fidelity",
        "rb_decay",
        "assignment_error",
        "average_gate_error",
    }
)


def _qubit_index(ref: str) -> Optional[int]:
    if isinstance(ref, str) and ref.startswith("$") and ref[1:].isdigit():
        return int(ref[1:])
    return None


def _coherence(datum) -> Optional[dict[str, Any]]:
    """{value, standardError?, unit:"S"} from a seconds datum."""
    if datum is None:
        return None
    out: dict[str, Any] = {"value": datum.value, "unit": "S"}
    if datum.std_error is not None:
        out["standardError"] = datum.std_error
    return out


def _fidelity_type(
    method: Optional[str],
    metric: Optional[str],
    *,
    on_readout: bool = False,
) -> Optional[str]:
    """Return a Braket ``fidelityType.name``, or None when naming one would invent it.

    A known method wins, including ``rb`` on a readout field: that is a
    protocol, not a readout fidelity. ``metric: readout_fidelity`` with no
    known protocol is ``READOUT``. An untyped number stored on
    ``readout.fidelity`` is ``READOUT`` because the field is the only signal.
    """
    if method and method in _FIDELITY_TYPE:
        return _FIDELITY_TYPE[method]
    if metric == "readout_fidelity":
        return "READOUT"
    if on_readout and metric not in _NOT_READOUT:
        return "READOUT"
    return None


def _fidelity_entry(value: float, ftype: str, std_error: Optional[float]) -> dict[str, Any]:
    entry: dict[str, Any] = {"fidelityType": {"name": ftype}, "fidelity": value}
    if std_error is not None:
        entry["standardError"] = std_error
    return entry


def _one_qubit_fidelity(props) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []

    # Readout fidelity. The type comes from method and metric. An rb method
    # stays randomized benchmarking; an untyped readout number is READOUT.
    ro = props.readout
    if ro is not None and ro.fidelity is not None:
        ftype = _fidelity_type(ro.fidelity.method, ro.fidelity.metric, on_readout=True)
        if ftype is not None:
            entries.append(_fidelity_entry(ro.fidelity.value, ftype, ro.fidelity.std_error))
        # Confusion-matrix off-diagonals -> directional readout error entries.
        cm = ro.confusion_matrix
        if cm and len(cm) == 2 and all(len(r) == 2 for r in cm):
            # Row i = P(assigned | prepared i); off-diagonals are errors.
            p1_given0 = cm[0][1]
            p0_given1 = cm[1][0]
            entries.append(
                {"fidelityType": {"name": "READOUT_ERROR_0_TO_1"}, "fidelity": p1_given0}
            )
            entries.append(
                {"fidelityType": {"name": "READOUT_ERROR_1_TO_0"}, "fidelity": p0_given1}
            )

    # Benchmark-based 1q fidelities (e.g. single-qubit RB).
    for bench in props.benchmarks or []:
        if bench.fidelity is None:
            continue
        ftype = _fidelity_type(bench.protocol, bench.fidelity.metric)
        if ftype is None:
            continue
        entries.append(_fidelity_entry(bench.fidelity.value, ftype, bench.fidelity.std_error))

    return entries


def to_braket_standardized(doc: OqCalDocument) -> dict[str, Any]:
    """Project an oq-cal document onto a Braket standardized-properties dict (v1)."""
    one_qubit: dict[str, dict[str, Any]] = {}
    if doc.qubits:
        for ref, props in doc.qubits.items():
            idx = _qubit_index(ref)
            if idx is None:
                continue
            entry: dict[str, Any] = {}
            t1 = _coherence(props.t1)
            t2 = _coherence(props.t2_echo or props.t2)
            if t1 is not None:
                entry["T1"] = t1
            if t2 is not None:
                entry["T2"] = t2
            fidelities = _one_qubit_fidelity(props)
            if fidelities:
                entry["oneQubitFidelity"] = fidelities
            if entry:
                one_qubit[str(idx)] = entry

    two_qubit: dict[str, dict[str, Any]] = {}
    for entry in doc.gates or []:
        if len(entry.qubits) != 2:
            continue
        idx = [_qubit_index(q) for q in entry.qubits]
        if any(i is None for i in idx):
            continue
        key = f"{idx[0]}-{idx[1]}"

        fidelities: list[dict[str, Any]] = []
        # Direct gate fidelity, only when its method names a Braket type.
        if entry.fidelity is not None:
            ftype = _fidelity_type(entry.fidelity.method, entry.fidelity.metric)
            if ftype is not None:
                fidelities.append(
                    _fidelity_entry(entry.fidelity.value, ftype, entry.fidelity.std_error)
                )
        elif entry.error is not None and entry.error.metric == "average_gate_error":
            # average_gate_error is 1 - F_avg. Invert only when the method also
            # names the Braket protocol. An unlabeled error stays an error.
            ftype = _fidelity_type(entry.error.method, None)
            if ftype is not None:
                fidelities.append(_fidelity_entry(1.0 - entry.error.value, ftype, None))
        # Benchmark fidelities attached to the gate.
        for bench in entry.benchmarks or []:
            if bench.fidelity is None:
                continue
            ftype = _fidelity_type(bench.protocol, bench.fidelity.metric)
            if ftype is None:
                continue
            fidelities.append(
                _fidelity_entry(bench.fidelity.value, ftype, bench.fidelity.std_error)
            )

        if not fidelities:
            continue
        two_qubit.setdefault(key, {})
        two_qubit[key]["twoQubitGateFidelity"] = [
            {"gateName": entry.name.upper(), **f} for f in fidelities
        ]

    result: dict[str, Any] = {
        "braketSchemaHeader": {"name": _SCHEMA_NAME, "version": _SCHEMA_VERSION},
    }
    if one_qubit:
        result["oneQubitProperties"] = one_qubit
    if two_qubit:
        result["twoQubitProperties"] = two_qubit
    return result


def _source_index(doc: OqCalDocument, ref: str) -> Optional[int]:
    """Vendor qubit index for export.

    A 1-based import stores the original number in ``qubit_labels``. Use that
    when it is an integer so the capabilities graph and the nested standardized
    block share one numbering. Otherwise use the ``$n`` index.
    """
    labels = doc.device.qubit_labels or {}
    label = labels.get(ref)
    if isinstance(label, str) and label.isdigit():
        return int(label)
    return _qubit_index(ref)


def _remap_index(doc: OqCalDocument, index: str) -> str:
    mapped = _source_index(doc, f"${index}")
    return str(mapped) if mapped is not None else index


def to_braket_rigetti(doc: OqCalDocument) -> dict[str, Any]:
    """Project an oq-cal document onto Rigetti device capabilities, version 2.

    Writes qubit count, directed coupling, pulse frames that carry
    ``frequency_hz``, and a nested standardized block when per-qubit or
    per-pair data exists. Does not invent a native gate set, ports, T1, or
    gate errors.
    """
    paradigm: dict[str, Any] = {
        "braketSchemaHeader": {"name": _PARADIGM_SCHEMA, "version": "1"},
    }
    if doc.device.num_qubits is not None:
        paradigm["qubitCount"] = doc.device.num_qubits

    graph: dict[str, list[str]] = {}
    for pair in doc.device.coupling_map or []:
        if len(pair) != 2:
            continue
        src = _source_index(doc, pair[0])
        dst = _source_index(doc, pair[1])
        if src is None or dst is None or src == dst:
            continue
        graph.setdefault(str(src), [])
        if str(dst) not in graph[str(src)]:
            graph[str(src)].append(str(dst))
    if graph:
        for dests in graph.values():
            dests.sort(key=int)
        paradigm["connectivity"] = {"fullyConnected": False, "connectivityGraph": graph}

    standardized = to_braket_standardized(doc)
    one = standardized.get("oneQubitProperties")
    two = standardized.get("twoQubitProperties")
    nested: Optional[dict[str, Any]] = None
    if one or two:
        nested = {"braketSchemaHeader": standardized["braketSchemaHeader"]}
        if one:
            nested["oneQubitProperties"] = {
                _remap_index(doc, key): value for key, value in one.items()
            }
        if two:
            nested["twoQubitProperties"] = {
                "-".join(_remap_index(doc, part) for part in key.split("-")): value
                for key, value in two.items()
            }

    frames: dict[str, Any] = {}
    for defcal in doc.defcals or []:
        frequency = (defcal.params or {}).get("frequency_hz")
        if isinstance(frequency, bool) or not isinstance(frequency, (int, float)):
            continue
        indices: list[int] = []
        ok = True
        for ref in defcal.qubits:
            idx = _source_index(doc, ref)
            if idx is None:
                ok = False
                break
            indices.append(idx)
        if not ok or not indices:
            continue
        frame_id = f"{defcal.gate}_q{'_'.join(str(i) for i in indices)}"
        frames[frame_id] = {
            "frameId": frame_id,
            "frequency": float(frequency),
            "associatedGate": defcal.gate,
            "qubitMappings": indices,
        }

    result: dict[str, Any] = {
        "braketSchemaHeader": {"name": _RIGETTI_SCHEMA, "version": "2"},
        "paradigm": paradigm,
    }
    if doc.snapshot.captured_at:
        result["service"] = {"updatedAt": doc.snapshot.captured_at}
    if nested is not None:
        result["standardized"] = nested
    if frames:
        result["pulse"] = {"frames": frames}
    return result


def to_braket(doc: OqCalDocument) -> dict[str, Any]:
    """Export to the Braket schema named by ``snapshot.source_schema``.

    Rigetti device capabilities stay a capabilities document. Everything else
    is standardized gate-model properties v1.
    """
    schema = doc.snapshot.source_schema or ""
    if "rigetti_device_capabilities" in schema:
        return to_braket_rigetti(doc)
    return to_braket_standardized(doc)


register_exporter("braket", to_braket)
