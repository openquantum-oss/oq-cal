"""Importer for AWS Braket Rigetti device capabilities.

Schema ``braket.device_schema.rigetti.rigetti_device_capabilities`` version 2
is a capabilities document: qubit count, a connectivity graph, an optional
embedded standardized-properties block, and optional pulse ports and frames.
It is not a T1 or gate-error table. This importer:

* reads ``paradigm.qubitCount`` and the directed edges of
  ``paradigm.connectivity.connectivityGraph``;
* when ``standardized`` is present, reuses the standardized-properties importer
  for the calibration it actually carries;
* turns a pulse frame into a defcal only when the frame publishes a frequency,
  an associated gate, and qubit mappings;
* leaves ports, native-gate lists, and the rest of the payload in
  ``extensions["braket"]``.

It does not invent T1, readout, or gate errors from the capabilities fields.
When ``provider.specs`` repeats a standardized T1 or T2 and the standardized
block omitted the standard error, that error is copied onto the datum. A
specs value that disagrees with the standardized value is left alone.
"""

from __future__ import annotations

from typing import Any, Optional

from ..models import Defcal, Device, Header, OqCalDocument, Snapshot
from ._identity import Identity, apply_identity
from .braket import BraketSchemaError, from_braket_standardized

RIGETTI_SCHEMA = "braket.device_schema.rigetti.rigetti_device_capabilities"

# associatedGate -> stdgates name where a standard name exists.
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
    "iswap": "iswap",
    "xy": "xy",
}


def _as_int(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _collect_indices(payload: dict) -> set[int]:
    indices: set[int] = set()
    paradigm = payload.get("paradigm") if isinstance(payload.get("paradigm"), dict) else {}
    graph = (paradigm.get("connectivity") or {}) if isinstance(paradigm, dict) else {}
    graph = graph.get("connectivityGraph") if isinstance(graph, dict) else None
    if isinstance(graph, dict):
        for raw_src, raw_dsts in graph.items():
            src = _as_int(raw_src)
            if src is not None:
                indices.add(src)
            if isinstance(raw_dsts, list):
                for raw_dst in raw_dsts:
                    dst = _as_int(raw_dst)
                    if dst is not None:
                        indices.add(dst)
    frames = (payload.get("pulse") or {}) if isinstance(payload.get("pulse"), dict) else {}
    frames = frames.get("frames") if isinstance(frames, dict) else None
    if isinstance(frames, dict):
        for frame in frames.values():
            if not isinstance(frame, dict):
                continue
            for qubit in frame.get("qubitMappings") or []:
                idx = _as_int(qubit)
                if idx is not None:
                    indices.add(idx)
    standardized = payload.get("standardized")
    if isinstance(standardized, dict):
        for key in standardized.get("oneQubitProperties") or {}:
            idx = _as_int(key)
            if idx is not None:
                indices.add(idx)
        for key in standardized.get("twoQubitProperties") or {}:
            for part in str(key).split("-"):
                idx = _as_int(part)
                if idx is not None:
                    indices.add(idx)
    return indices


def _shift_standardized(standardized: dict, shift: int) -> dict:
    """Return a copy whose qubit keys use the same shift as the outer document.

    The standardized importer applies the 1-based shift on its own. Pre-shifting
    here keeps a 1-based capabilities graph and a 1-based nested table on one
    numbering, and leaves the object stored in ``extensions`` untouched.
    """
    if shift == 0:
        return standardized
    one: dict[str, Any] = {}
    for key, value in (standardized.get("oneQubitProperties") or {}).items():
        idx = _as_int(key)
        if idx is None:
            continue
        one[str(idx - shift)] = value
    two: dict[str, Any] = {}
    for key, value in (standardized.get("twoQubitProperties") or {}).items():
        parts: list[str] = []
        ok = True
        for part in str(key).split("-"):
            idx = _as_int(part)
            if idx is None:
                ok = False
                break
            parts.append(str(idx - shift))
        if ok:
            two["-".join(parts)] = value
    rewritten = dict(standardized)
    rewritten["oneQubitProperties"] = one
    rewritten["twoQubitProperties"] = two
    return rewritten


def _graph_edges(payload: dict, shift: int) -> set[tuple[int, int]]:
    paradigm = payload.get("paradigm") if isinstance(payload.get("paradigm"), dict) else {}
    connectivity = paradigm.get("connectivity") if isinstance(paradigm, dict) else None
    graph = connectivity.get("connectivityGraph") if isinstance(connectivity, dict) else None
    edges: set[tuple[int, int]] = set()
    if not isinstance(graph, dict):
        return edges
    for raw_src, raw_dsts in graph.items():
        src = _as_int(raw_src)
        if src is None or not isinstance(raw_dsts, list):
            continue
        for raw_dst in raw_dsts:
            dst = _as_int(raw_dst)
            if dst is None or dst == src:
                continue
            edges.add((src - shift, dst - shift))
    return edges


def _pulse_defcals(payload: dict, shift: int) -> list[Defcal]:
    pulse = payload.get("pulse") if isinstance(payload.get("pulse"), dict) else {}
    frames = pulse.get("frames") if isinstance(pulse, dict) else None
    if not isinstance(frames, dict):
        return []
    defcals: list[Defcal] = []
    for frame in frames.values():
        if not isinstance(frame, dict):
            continue
        frequency = frame.get("frequency")
        gate = frame.get("associatedGate")
        mappings = frame.get("qubitMappings")
        if isinstance(frequency, bool) or not isinstance(frequency, (int, float)):
            continue
        if not isinstance(gate, str) or not gate:
            continue
        if not isinstance(mappings, list) or not mappings:
            continue
        qubits: list[str] = []
        ok = True
        for mapping in mappings:
            idx = _as_int(mapping)
            if idx is None:
                ok = False
                break
            qubits.append(f"${idx - shift}")
        if not ok:
            continue
        name = _GATE_NAME.get(gate.lower(), gate.lower())
        defcals.append(
            Defcal(gate=name, qubits=qubits, params={"frequency_hz": float(frequency)})
        )
    defcals.sort(key=lambda item: (item.gate, tuple(item.qubits), item.params["frequency_hz"]))
    return defcals


def _specs_coherence(payload: dict) -> dict[int, dict[str, tuple[float, float]]]:
    """Node index to ``{t1|t2: (value, error)}`` from Rigetti specs benchmarks.

    FreeInversionRecovery is T1. FreeInductionDecay is T2. Each characteristic
    is one node. The error is the standard error the standardized copy drops.
    """
    provider = payload.get("provider") if isinstance(payload.get("provider"), dict) else {}
    specs = provider.get("specs") if isinstance(provider, dict) else None
    benchmarks = specs.get("benchmarks") if isinstance(specs, dict) else None
    if not isinstance(benchmarks, list):
        return {}
    fields = {
        "FreeInversionRecovery": ("t1", "T1"),
        "FreeInductionDecay": ("t2", "T2"),
    }
    found: dict[int, dict[str, tuple[float, float]]] = {}
    for bench in benchmarks:
        if not isinstance(bench, dict):
            continue
        mapped = fields.get(str(bench.get("name")))
        if mapped is None:
            continue
        field, characteristic = mapped
        for site in bench.get("sites") or []:
            if not isinstance(site, dict):
                continue
            site_nodes = site.get("node_ids") or []
            for entry in site.get("characteristics") or []:
                if not isinstance(entry, dict) or entry.get("name") != characteristic:
                    continue
                node_ids = entry.get("node_ids") or site_nodes
                if not isinstance(node_ids, list) or len(node_ids) != 1:
                    continue
                index = _as_int(node_ids[0])
                value = entry.get("value")
                error = entry.get("error")
                value_ok = not isinstance(value, bool) and isinstance(value, (int, float))
                error_ok = not isinstance(error, bool) and isinstance(error, (int, float))
                if index is None or not value_ok or not error_ok or error <= 0:
                    continue
                found.setdefault(index, {})[field] = (float(value), float(error))
    return found


def _fill_specs_standard_errors(doc: OqCalDocument, payload: dict, shift: int) -> None:
    if not doc.qubits:
        return
    for index, fields in _specs_coherence(payload).items():
        props = doc.qubits.get(f"${index - shift}")
        if props is None:
            continue
        for field, (value, error) in fields.items():
            datum = getattr(props, field)
            if datum is None or datum.std_error is not None:
                continue
            tolerance = max(1e-18, 1e-9 * abs(value))
            if abs(datum.value - value) > tolerance:
                continue
            datum.std_error = error


def from_braket_rigetti(
    payload: dict,
    *,
    device_id: Optional[str] = None,
    vendor: Optional[str] = None,
    model: Optional[str] = None,
    captured_at: Optional[str] = None,
    snapshot_id: Optional[str] = None,
    num_qubits: Optional[int] = None,
) -> OqCalDocument:
    """Convert a Rigetti device-capabilities payload to a :class:`OqCalDocument`."""
    header = payload.get("braketSchemaHeader") or {}
    if header.get("name") != RIGETTI_SCHEMA:
        raise BraketSchemaError(
            f"unsupported Braket schema {header.get('name')!r}; expected {RIGETTI_SCHEMA!r}"
        )
    version = str(header.get("version", ""))
    if version != "2":
        raise BraketSchemaError(
            f"unsupported {RIGETTI_SCHEMA} version {version!r}; supported: 2"
        )

    indices = _collect_indices(payload)
    shift = 1 if (0 not in indices and 1 in indices) else 0

    standardized = payload.get("standardized")
    if isinstance(standardized, dict):
        doc = from_braket_standardized(_shift_standardized(standardized, shift))
    else:
        doc = OqCalDocument(
            oq_cal=Header(version="0.1"),
            device=Device(id="braket-device"),
            snapshot=Snapshot(source="aws-braket"),
        )

    device = doc.device
    paradigm = payload.get("paradigm") if isinstance(payload.get("paradigm"), dict) else {}
    qubit_count = paradigm.get("qubitCount") if isinstance(paradigm, dict) else None
    counts: list[int] = []
    if isinstance(qubit_count, int) and not isinstance(qubit_count, bool):
        counts.append(qubit_count)
    if indices:
        counts.append(max(indices) - shift + 1)
    if device.num_qubits is not None:
        counts.append(device.num_qubits)
    if num_qubits is not None:
        counts.append(num_qubits)
    if counts:
        device.num_qubits = max(counts)

    edges = _graph_edges(payload, shift)
    if edges:
        device.coupling_map = [[f"${i}", f"${j}"] for i, j in sorted(edges)]
    if shift and indices:
        device.qubit_labels = {f"${idx - shift}": str(idx) for idx in sorted(indices)}

    defcals = _pulse_defcals(payload, shift)
    if defcals:
        doc.defcals = list(doc.defcals or []) + defcals
    _fill_specs_standard_errors(doc, payload, shift)

    service = payload.get("service") if isinstance(payload.get("service"), dict) else {}
    if isinstance(service, dict) and service.get("updatedAt"):
        doc.snapshot.captured_at = service["updatedAt"]
    doc.snapshot.source = "aws-braket"
    doc.snapshot.source_schema = f"{RIGETTI_SCHEMA} v2"
    doc.extensions = {"braket": payload}

    apply_identity(
        device,
        doc.snapshot,
        Identity(
            device_id=device_id,
            vendor=vendor,
            model=model,
            captured_at=captured_at,
            snapshot_id=snapshot_id,
        ),
    )
    return doc
