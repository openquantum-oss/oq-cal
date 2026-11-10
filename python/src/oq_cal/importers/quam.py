"""Importer for a QUAM (Quantum Abstraction Machine) ``state.json`` tree.

QUAM is the persistent state of a QUAlibrate deployment: a component tree with
``__class__`` type tags and a ``#/...`` string reference system. It is a
control-stack model, not a characterization report, but its superconducting
component vocabulary carries enough overlap (T1/T2, resonance frequencies, pulse
amp/length/DRAG) to extract a useful oq-cal document.

The importer is deliberately duck-typed and tolerant: field names vary across
labs' custom components, so recognition is case-insensitive and best-effort, and
missing fields are simply skipped. It never raises on a thin tree. A document
with only the required sections is a valid result. The full tree is preserved under
``extensions["quam"]``.

**Pulse length:** ``length`` is a sample count. The importer looks for a sample
rate in hertz (``sampling_rate``, ``sample_rate``, ``clock``,
``sampling_rate_hz``, ``sample_rate_hz``) on the pulse, then the channel, then
the component, then the tree root. Duration in seconds is ``length / rate``.
When no rate is present, the QUA convention of 1 GS/s is used, so a length in
samples equals a length in nanoseconds. Pulse ``amplitude`` is a dimensionless
drive amplitude.
"""

from __future__ import annotations

from typing import Any, Optional

from ..models import (
    Datum,
    Defcal,
    Device,
    Header,
    OqCalDocument,
    QubitProperties,
    Snapshot,
)
from ..registry import register_importer
from ._identity import Identity, apply_identity

# recognizable pulse op name -> stdgates gate name.
_PULSE_GATE = {
    "x180": "x",
    "x90": "sx",
    "y180": "y",
    "y90": "sy",
    "measure": "measure",
    "readout": "measure",
}

_NS_PER_SAMPLE = 1e-9  # default QUA 1 GS/s: length in samples == nanoseconds.
_RATE_KEYS = (
    "sampling_rate",
    "sample_rate",
    "clock",
    "sampling_rate_hz",
    "sample_rate_hz",
)


def _coupling_map(pairs: set[tuple[int, int]]) -> list[list[str]]:
    """Emit DIRECTED coupling-map pairs (both directions) from undirected pairs,
    sorted numerically by ``(i, j)``."""
    directed: set[tuple[int, int]] = set()
    for i, j in pairs:
        directed.add((i, j))
        directed.add((j, i))
    return [[f"${i}", f"${j}"] for i, j in sorted(directed)]


def _resolve(root: dict, value: Any) -> Any:
    """Resolve an absolute ``#/...`` reference against ``root``; tolerate failure."""
    if not (isinstance(value, str) and value.startswith("#/")):
        return value
    path = value[2:].split("/")
    node: Any = root
    for part in path:
        if isinstance(node, dict) and part in node:
            node = node[part]
        else:
            return None  # unresolvable (or relative #./ #../) -> skip
    return node


def _get_ci(d: dict, *names: str) -> Any:
    """Case-insensitive lookup over several candidate keys."""
    lower = {k.lower(): v for k, v in d.items()}
    for name in names:
        if name.lower() in lower:
            return lower[name.lower()]
    return None


def _seconds_per_sample(*nodes: Any) -> float:
    """Seconds per sample from the first explicit rate, else the 1 GS/s default."""
    for node in nodes:
        if not isinstance(node, dict):
            continue
        raw = _get_ci(node, *_RATE_KEYS)
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            continue
        if raw > 0:
            return 1.0 / float(raw)
    return _NS_PER_SAMPLE


def _num_datum(raw: Any, unit: str) -> Optional[Datum]:
    if raw is None or isinstance(raw, (dict, list, str)):
        return None
    try:
        return Datum(value=float(raw), unit=unit)
    except (TypeError, ValueError):
        return None


def _is_qubit_like(key: str, value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    cls = str(value.get("__class__", "")).lower()
    return "transmon" in cls or "qubit" in cls


def _extract_qubit(comp: dict) -> QubitProperties:
    qp = QubitProperties()
    qp.t1 = _num_datum(_get_ci(comp, "T1", "t1"), "s")
    qp.t2 = _num_datum(_get_ci(comp, "T2", "t2", "T2ramsey", "t2_ramsey"), "s")
    qp.t2_echo = _num_datum(_get_ci(comp, "T2echo", "t2_echo", "T2_echo"), "s")
    qp.frequency_01 = _num_datum(
        _get_ci(comp, "f_01", "frequency", "resonance_frequency", "freq_01"), "Hz"
    )
    qp.anharmonicity = _num_datum(_get_ci(comp, "anharmonicity", "anharm"), "Hz")
    return qp


def _pulse_params(pulse: dict, seconds_per_sample: float) -> dict[str, Any]:
    p: dict[str, Any] = {}
    amp = _get_ci(pulse, "amplitude", "amp")
    if isinstance(amp, (int, float)) and not isinstance(amp, bool):
        p["amp"] = float(amp)
    length = _get_ci(pulse, "length", "duration")
    if isinstance(length, (int, float)) and not isinstance(length, bool):
        p["duration_s"] = float(length) * seconds_per_sample
    alpha = _get_ci(pulse, "alpha", "motzoi", "drag")
    if isinstance(alpha, (int, float)) and not isinstance(alpha, bool):
        p["motzoi"] = float(alpha)
    return p


def _extract_defcals(
    comp: dict, ref: str, root: dict, index_to_ref: dict[int, str]
) -> list[Defcal]:
    """Pull defcals from a qubit's channels/operations (and coupler pairs)."""
    defcals: list[Defcal] = []
    for chan_key in ("xy", "resonator", "z", "drive"):
        chan = comp.get(chan_key)
        chan = _resolve(root, chan)
        if not isinstance(chan, dict):
            continue
        ops = chan.get("operations")
        if not isinstance(ops, dict):
            continue
        for op_name, pulse in ops.items():
            pulse = _resolve(root, pulse)
            if not isinstance(pulse, dict):
                continue
            gate = _PULSE_GATE.get(op_name.lower())
            if gate is None:
                continue
            params = _pulse_params(pulse, _seconds_per_sample(pulse, chan, comp, root))
            defcals.append(Defcal(gate=gate, qubits=[ref], params=params or None))
    return defcals


def from_quam_state(
    payload: dict,
    *,
    device_id: Optional[str] = None,
    vendor: Optional[str] = None,
    model: Optional[str] = None,
    captured_at: Optional[str] = None,
    snapshot_id: Optional[str] = None,
) -> OqCalDocument:
    """Convert a QUAM ``state.json`` tree to a :class:`OqCalDocument`.

    Never raises on missing fields. A document with only the required sections
    is a valid result. ``device_id``, ``vendor``, ``model``, ``captured_at`` and
    ``snapshot_id`` are optional identity / provenance overrides: a supplied value
    OVERRIDES the source-derived value, an omitted one leaves current behavior.
    """
    root = payload

    # Locate the qubit container: an explicit "qubits" map, else any dict whose
    # values are qubit-like components.
    qubit_container: dict[str, Any] = {}
    if isinstance(payload.get("qubits"), dict):
        qubit_container = payload["qubits"]
    else:
        for value in payload.values():
            if isinstance(value, dict) and any(
                _is_qubit_like(k, v) for k, v in value.items()
            ):
                qubit_container = {
                    k: v for k, v in value.items() if _is_qubit_like(k, v)
                }
                break

    # Deterministic ordering; honor a numeric "id" when present.
    def sort_key(item: tuple[str, Any]) -> tuple[int, str]:
        _, comp = item
        cid = comp.get("id") if isinstance(comp, dict) else None
        return (cid if isinstance(cid, int) else 1 << 30, item[0])

    ordered = sorted(
        ((k, v) for k, v in qubit_container.items() if _is_qubit_like(k, v)),
        key=sort_key,
    )

    name_to_ref: dict[str, str] = {}
    index_to_ref: dict[int, str] = {}
    ref_to_label: dict[str, str] = {}
    qubits: dict[str, QubitProperties] = {}
    defcals: list[Defcal] = []

    for i, (name, comp) in enumerate(ordered):
        ref = f"${i}"
        name_to_ref[name] = ref
        ref_to_label[ref] = name
        cid = comp.get("id")
        if isinstance(cid, int):
            index_to_ref[cid] = ref

        qp = _extract_qubit(comp)
        if qp.model_dump(exclude_none=True):
            qubits[ref] = qp
        defcals.extend(_extract_defcals(comp, ref, root, index_to_ref))

    # qubit_pairs -> two-qubit defcals (e.g. cz on a coupler)
    pairs = payload.get("qubit_pairs")
    if isinstance(pairs, dict):
        for _pname, pair in pairs.items():
            if not isinstance(pair, dict):
                continue
            ctrl = _resolve(root, pair.get("qubit_control"))
            tgt = _resolve(root, pair.get("qubit_target"))
            refs: list[str] = []
            for node in (ctrl, tgt):
                if isinstance(node, dict):
                    # find this node's name among the qubit container
                    for name, comp in ordered:
                        if comp is node:
                            refs.append(name_to_ref[name])
                            break
            coupler = _resolve(root, pair.get("coupler"))
            if isinstance(coupler, dict) and len(refs) == 2:
                ops = coupler.get("operations")
                if isinstance(ops, dict):
                    for op_name, pulse in ops.items():
                        pulse = _resolve(root, pulse)
                        if not isinstance(pulse, dict):
                            continue
                        gate = _PULSE_GATE.get(op_name.lower(), op_name.lower())
                        defcals.append(
                            Defcal(
                                gate=gate,
                                qubits=refs,
                                params=_pulse_params(
                                    pulse, _seconds_per_sample(pulse, coupler, root)
                                )
                                or None,
                            )
                        )

    num_qubits = len(ordered)

    # coupling_map from the two-qubit evidence actually extracted (2q defcals).
    pair_evidence: set[tuple[int, int]] = set()
    for dc in defcals:
        if len(dc.qubits) == 2:
            pair_evidence.add((int(dc.qubits[0][1:]), int(dc.qubits[1][1:])))

    # device identity: source name field, else a sensible default. A supplied
    # device_id override is applied below via apply_identity.
    dev_id = _get_ci(payload, "name", "id") or "quam-device"
    if not isinstance(dev_id, str):
        dev_id = "quam-device"

    device = Device(id=dev_id, num_qubits=num_qubits)
    if ref_to_label:
        device.qubit_labels = ref_to_label
    if pair_evidence:
        device.coupling_map = _coupling_map(pair_evidence)

    snapshot = Snapshot(source="quam-state", source_schema="quam-state.json")

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
        extensions={"quam": payload},
    )
    if qubits:
        doc.qubits = qubits
    if defcals:
        doc.defcals = defcals
    return doc


register_importer("quam-state", from_quam_state)
