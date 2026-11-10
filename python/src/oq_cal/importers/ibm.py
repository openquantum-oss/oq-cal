"""Importer for a Qiskit ``BackendProperties.to_dict()`` payload.

IBM Quantum publishes calibration as a properties dictionary, not as a Braket
standardized-properties document. The shape is::

    {
      "backend_name": "...",
      "last_update_date": "<ISO-8601>",
      "qubits": [[{"name": "T1", "value": 20.0, "unit": "us"}, ...], ...],
      "gates": [{"gate": "cx", "qubits": [0, 1], "parameters": [...]}]
    }

Qubit index is the list index and is already 0-based. Times and frequencies
are converted to seconds and hertz. ``gate_error`` is stored as an error
(``metric: average_gate_error``), not inverted into a fidelity. ``readout_error``
is an assignment error. ``prob_meas0_prep1`` and ``prob_meas1_prep0`` become a
row-stochastic confusion matrix. The payload is kept under ``extensions["ibm"]``.

This module does not import Qiskit. A properties dictionary is plain JSON.
"""

from __future__ import annotations

from typing import Any, Optional

from ..models import (
    Benchmark,
    Datum,
    Device,
    GateEntry,
    Header,
    OqCalDocument,
    QubitProperties,
    Readout,
    Snapshot,
)
from ..registry import register_importer
from ._identity import Identity, apply_identity

_TIME = {
    "": 1.0,
    "s": 1.0,
    "sec": 1.0,
    "ms": 1e-3,
    "us": 1e-6,
    "µs": 1e-6,
    "ns": 1e-9,
    "ps": 1e-12,
}
_FREQ = {"hz": 1.0, "khz": 1e3, "mhz": 1e6, "ghz": 1e9}
_GATE_NAME = {
    "cnot": "cx",
    "cx": "cx",
    "cz": "cz",
    "ecr": "ecr",
    "swap": "swap",
    "ccx": "ccx",
    "x": "x",
    "sx": "sx",
    "rx": "rx",
    "ry": "ry",
    "rz": "rz",
    "id": "id",
    "h": "h",
    "s": "s",
    "sdg": "sdg",
    "t": "t",
    "tdg": "tdg",
    "reset": "reset",
}


class IBMPropertiesError(ValueError):
    """Raised when a payload is not a BackendProperties dictionary."""


def _rfc3339(value: Any) -> Optional[str]:
    if not isinstance(value, str) or not value:
        return None
    if len(value) >= 11 and value[10] == " ":
        return value[:10] + "T" + value[11:]
    return value


def _as_float(value: Any) -> Optional[float]:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _nduv(entries: Any) -> dict[str, dict]:
    found: dict[str, dict] = {}
    if not isinstance(entries, list):
        return found
    for entry in entries:
        if isinstance(entry, dict) and isinstance(entry.get("name"), str):
            found[entry["name"]] = entry
    return found


def _scale(entry: dict, table: dict[str, float]) -> Optional[float]:
    value = _as_float(entry.get("value"))
    if value is None:
        return None
    unit = str(entry.get("unit") or "").strip().lower().replace("μ", "µ")
    factor = table.get(unit)
    if factor is None:
        return value
    return value * factor


def _stamp(entry: dict) -> Optional[str]:
    return _rfc3339(entry.get("date"))


def _time_datum(entry: Optional[dict]) -> Optional[Datum]:
    if not isinstance(entry, dict):
        return None
    value = _scale(entry, _TIME)
    if value is None:
        return None
    return Datum(value=value, unit="s", updated_at=_stamp(entry))


def _freq_datum(entry: Optional[dict]) -> Optional[Datum]:
    if not isinstance(entry, dict):
        return None
    value = _scale(entry, _FREQ)
    if value is None:
        return None
    return Datum(value=value, unit="Hz", updated_at=_stamp(entry))


def _dimensionless(entry: Optional[dict], **extra: Any) -> Optional[Datum]:
    if not isinstance(entry, dict):
        return None
    value = _as_float(entry.get("value"))
    if value is None:
        return None
    return Datum(value=value, unit="dimensionless", updated_at=_stamp(entry), **extra)


def _build_qubit(entries: Any) -> tuple[Optional[QubitProperties], bool]:
    """Return ``(properties, keep)``. An empty property list is still a qubit."""
    if not isinstance(entries, list):
        return None, False
    fields = _nduv(entries)
    qp = QubitProperties()
    qp.t1 = _time_datum(fields.get("T1"))
    qp.t2 = _time_datum(fields.get("T2"))
    qp.frequency_01 = _freq_datum(fields.get("frequency"))
    qp.anharmonicity = _freq_datum(fields.get("anharmonicity"))

    readout = Readout()
    duration = _time_datum(fields.get("readout_length"))
    if duration is not None:
        readout.duration = duration
    p_meas1_prep0 = _as_float((fields.get("prob_meas1_prep0") or {}).get("value"))
    p_meas0_prep1 = _as_float((fields.get("prob_meas0_prep1") or {}).get("value"))
    if p_meas1_prep0 is not None or p_meas0_prep1 is not None:
        a = p_meas1_prep0 or 0.0  # P(assign 1 | prepared 0)
        b = p_meas0_prep1 or 0.0  # P(assign 0 | prepared 1)
        readout.confusion_matrix = [[1.0 - a, a], [b, 1.0 - b]]
    if readout.model_dump(exclude_none=True):
        qp.readout = readout

    # readout_error is the published assignment error. Do not invert it into
    # a fidelity the properties dictionary did not report.
    assignment = _dimensionless(fields.get("readout_error"), metric="assignment_error")
    if assignment is not None:
        qp.benchmarks = [
            Benchmark(protocol="readout", error=assignment, qubits=None)
        ]

    if qp.model_dump(exclude_none=True):
        return qp, True
    return None, True


def _build_gate(raw: dict) -> Optional[GateEntry]:
    name = raw.get("gate")
    qubits = raw.get("qubits")
    if not isinstance(name, str) or not isinstance(qubits, list) or not qubits:
        return None
    if name.lower() == "measure":
        # Readout is taken from the per-qubit properties, not a measure "gate".
        return None
    refs: list[str] = []
    for qubit in qubits:
        idx = _as_int_index(qubit)
        if idx is None:
            return None
        refs.append(f"${idx}")
    params = _nduv(raw.get("parameters"))
    error = _dimensionless(params.get("gate_error"), metric="average_gate_error")
    duration = _time_datum(params.get("gate_length"))
    if error is None and duration is None:
        return None
    gate_name = _GATE_NAME.get(name.lower(), name.lower())
    return GateEntry(name=gate_name, qubits=refs, error=error, duration=duration)


def _as_int_index(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def from_ibm_properties(
    payload: dict,
    *,
    device_id: Optional[str] = None,
    vendor: Optional[str] = None,
    model: Optional[str] = None,
    captured_at: Optional[str] = None,
    snapshot_id: Optional[str] = None,
    num_qubits: Optional[int] = None,
) -> OqCalDocument:
    """Convert a Qiskit backend-properties dictionary to a :class:`OqCalDocument`."""
    qubits_raw = payload.get("qubits")
    if not isinstance(qubits_raw, list):
        raise IBMPropertiesError(
            "IBM properties payload needs a 'qubits' list "
            "(Qiskit BackendProperties.to_dict())"
        )

    qubits: dict[str, QubitProperties] = {}
    for index, entries in enumerate(qubits_raw):
        props, keep = _build_qubit(entries)
        if keep and props is not None:
            qubits[f"${index}"] = props

    gates: list[GateEntry] = []
    for raw in payload.get("gates") or []:
        if isinstance(raw, dict):
            gate = _build_gate(raw)
            if gate is not None:
                gates.append(gate)

    pairs: set[tuple[int, int]] = set()
    for gate in gates:
        if len(gate.qubits) == 2:
            pairs.add((int(gate.qubits[0][1:]), int(gate.qubits[1][1:])))

    roster = len(qubits_raw)
    if num_qubits is not None:
        roster = max(roster, num_qubits)
    backend_name = payload.get("backend_name")
    device = Device(
        id=backend_name if isinstance(backend_name, str) and backend_name else "ibm-device",
        num_qubits=roster,
    )
    if pairs:
        device.coupling_map = [[f"${i}", f"${j}"] for i, j in sorted(pairs)]

    snapshot = Snapshot(
        source="ibm-properties",
        source_schema="qiskit.providers.models.BackendProperties",
        captured_at=_rfc3339(payload.get("last_update_date")),
    )
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
        extensions={"ibm": payload},
    )
    if qubits:
        doc.qubits = qubits
    if gates:
        doc.gates = gates
    return doc


register_importer("ibm-properties", from_ibm_properties)
