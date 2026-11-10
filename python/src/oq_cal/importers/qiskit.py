"""Importer for a Qiskit :class:`~qiskit.transpiler.Target`.

A ``Target`` is Qiskit's in-memory model of a backend's instructions and their
calibrated properties. It has no stable on-disk serialization, so this importer
is the bridge from a live transpiler target into a portable oq-cal document.

Extraction:

* ``Target.num_qubits`` -> ``device.num_qubits``;
* ``Target.qubit_properties[i]`` (``t1``, ``t2`` in seconds, ``frequency`` in
  Hz) -> ``qubits["$i"]``;
* per-instruction ``InstructionProperties`` (``duration`` in seconds, ``error``
  dimensionless) -> ``gates[]`` entries, one per (instruction, qargs) pair;
* the ``measure`` instruction's ``error`` becomes a per-qubit readout fidelity
  (``1 - error``, method ``qiskit_target``) rather than a gate entry.

There is **no** ``extensions`` payload: a ``Target`` is not JSON-serializable,
so a verbatim round-trippable copy cannot be stored. The conversion is therefore
lossy with respect to non-standardized target internals (timing constraints,
calibration schedules, etc.).

This module registers a thin ``dict -> OqCalDocument`` wrapper under
``"qiskit-target"`` for registry symmetry; it raises if invoked with a plain
dict, since a live ``Target`` object (not JSON) is required. Direct callers
should use :func:`from_qiskit_target`.
"""

from __future__ import annotations

from typing import Any, Optional

from ..models import (
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


def from_qiskit_target(
    target: Any,
    *,
    device_id: str,
    vendor: Optional[str] = None,
    model: Optional[str] = None,
    captured_at: Optional[str] = None,
    snapshot_id: Optional[str] = None,
) -> OqCalDocument:
    """Convert a Qiskit ``Target`` to a :class:`OqCalDocument`.

    ``device_id`` is required (a ``Target`` carries no device identity).
    ``vendor``, ``model``, ``captured_at`` and ``snapshot_id`` are optional
    identity / provenance overrides with the same semantics as the other
    importers: a supplied value OVERRIDES the source-derived value.
    """
    num_qubits = int(target.num_qubits)

    # Per-qubit properties.
    qubits: dict[str, QubitProperties] = {}
    qprops = getattr(target, "qubit_properties", None)
    if qprops:
        for i, qp in enumerate(qprops):
            if qp is None:
                continue
            entry = QubitProperties()
            t1 = getattr(qp, "t1", None)
            t2 = getattr(qp, "t2", None)
            freq = getattr(qp, "frequency", None)
            if t1 is not None:
                entry.t1 = Datum(value=float(t1), unit="s")
            if t2 is not None:
                entry.t2 = Datum(value=float(t2), unit="s")
            if freq is not None:
                entry.frequency_01 = Datum(value=float(freq), unit="Hz")
            if entry.model_dump(exclude_none=True):
                qubits[f"${i}"] = entry

    # Instructions -> gates, with "measure" folded into per-qubit readout.
    gates: list[GateEntry] = []
    for name in target.operation_names:
        try:
            props = target[name]
        except (KeyError, TypeError):
            continue
        if props is None:
            continue
        for qargs, ip in props.items():
            if qargs is None:
                continue
            refs = [f"${q}" for q in qargs]
            duration = getattr(ip, "duration", None) if ip is not None else None
            error = getattr(ip, "error", None) if ip is not None else None

            if name == "measure":
                if error is None or not refs:
                    continue
                ref = refs[0]
                qp = qubits.setdefault(ref, QubitProperties())
                ro = qp.readout or Readout()
                ro.fidelity = Datum(
                    value=1.0 - float(error),
                    unit="dimensionless",
                    method="qiskit_target",
                    metric="readout_fidelity",
                )
                if duration is not None:
                    ro.duration = Datum(value=float(duration), unit="s")
                qp.readout = ro
                continue

            ge = GateEntry(name=name, qubits=refs)
            if error is not None:
                ge.error = Datum(
                    value=float(error),
                    unit="dimensionless",
                    metric="average_gate_error",
                )
            if duration is not None:
                ge.duration = Datum(value=float(duration), unit="s")
            gates.append(ge)

    device = Device(id=device_id, num_qubits=num_qubits)

    snapshot = Snapshot(source="qiskit-target", source_schema="qiskit.transpiler.Target")

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
    )
    if qubits:
        # Re-sort by index for deterministic output.
        doc.qubits = {k: qubits[k] for k in sorted(qubits, key=lambda s: int(s[1:]))}
    if gates:
        doc.gates = gates
    return doc


def _registry_wrapper(_payload: dict) -> OqCalDocument:
    """Registry shim: the qiskit importer needs a live Target, not a dict."""
    raise TypeError(
        "the 'qiskit-target' importer requires a qiskit.transpiler.Target object; "
        "call oq_cal.importers.qiskit.from_qiskit_target(target, device_id=...) directly"
    )


register_importer("qiskit-target", _registry_wrapper)
