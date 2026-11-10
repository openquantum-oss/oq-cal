"""Importer for a Boulder Opal calibration snapshot (Q-CTRL product).

Boulder Opal snapshots come from control-stack tooling that sits at the
hardware edge and emits a device-wide calibration state. The snapshot is the
richest source in the fixture set: per-datum asymmetric
uncertainty, per-datum status and timestamps, per-qubit readout classifiers,
and pulse-level defcals. Its top-level shape is::

    {
      "version": "<iso-ish timestamp string>",
      "qpu_model": "<model>",
      "enabled_qubits": ["qA1", ...],   # vendor labels
      "components": { "qA1": {...transmon...}, "rA0": {...resonator...}, ... },
      "classifiers": { "qA1": {...linear-IQ...}, ... },
      "defcals": { "x:qA1": {...}, "cz:qA1_qA3": {...}, ... },
      "gate_errors": [ {gate, qubits, value, ...}, ... ],
      "qubit_cal": [ {"qubit": "qA1", "operational": true, "t1": {...}}, ... ]
    }

``qubit_cal``, when present, is the preferred source for per-qubit coherence
and frequency: its values are already in seconds and hertz. ``components``
remains the source for pulses, bias, and classifiers, and is the fallback when
``qubit_cal`` is absent. A null ``qubit_cal`` field is omitted, not stored as 0.

Values appear in mixed shapes: bare floats, structured dicts with
``{value, err_minus, err_plus, calibration_status, updated_at}``, duration
dicts nesting ``{value: {value, unit: "ns"}}``, and error bars that are
themselves duration dicts. All are normalized to the oq-cal datum shape with SI
units. The full payload is preserved under ``extensions["boulder_opal"]``.

Wiring, resonator parameters, and amplifier settings stay in that extension.
``$n`` is assigned from the full qubit roster (``qubit_cal`` order, otherwise
the sorted union of transmon labels and ``enabled_qubits``), so disabling a
qubit does not renumber the others.
"""

from __future__ import annotations

import math
from typing import Any, Optional

from ..models import (
    Benchmark,  # noqa: F401  (kept for parity / future use)
    Classifier,
    Datum,
    Defcal,
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

# calibration_status values map 1:1 to oq-cal datum status vocabulary.
_STATUS = {"good", "approximate", "stale", "bad", "unmeasured"}

_GATE_NAME = {
    "x": "x",
    "y": "y",
    "z": "z",
    "h": "h",
    "s": "s",
    "sx": "sx",
    "sy": "sy",
    "rz": "rz",
    "cz": "cz",
    "cx": "cx",
    "swap": "swap",
    "measure": "measure",
    "x90": "sx",
    "cphase": "cz",
    "cnot": "cx",
}


# oq-cal confusion matrices are row-stochastic. Boulder stores the transpose
# (columns sum to 1). Transpose when the columns fit that rule more tightly.
_CM_TOL = 0.02

# qubit_cal field, component field, oq-cal field, unit, whether it is a time.
_QUBIT_FIELDS = (
    ("frequency", "freq_01", "frequency_01", "Hz", False),
    ("anharmonicity", "anharm", "anharmonicity", "Hz", False),
    ("t1", "t1", "t1", "s", True),
    ("t2", "t2", "t2", "s", True),
    ("t2_echo", "t2_echo", "t2_echo", "s", True),
)


def _unit_to_seconds(value: float, unit: Optional[str]) -> float:
    u = (unit or "").lower()
    if u == "ns":
        return value * 1e-9
    if u == "us":
        return value * 1e-6
    if u == "ms":
        return value * 1e-3
    return value  # "s" or unknown: pass through


def _rfc3339(raw: str) -> str:
    """Rewrite ``YYYY-MM-DD HH:MM:SS`` timestamps into RFC 3339."""
    if len(raw) >= 11 and raw[10] == " ":
        return raw[:10] + "T" + raw[11:]
    return raw


def _error_number(raw: Any, factor: float) -> Optional[float]:
    """Read an error bar that is a number or a ``{value, unit}`` duration.

    A bare number is in the same unit as the unscaled source value, so
    ``factor`` (SI value / source value) brings it into the datum's unit. A
    duration object carries its own unit and is converted directly.
    """
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        return float(raw) * factor
    if isinstance(raw, dict):
        val = raw.get("value")
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            return None
        unit = raw.get("unit")
        if isinstance(unit, str) or raw.get("dtype") == "duration":
            return _unit_to_seconds(float(val), unit if isinstance(unit, str) else None)
        return float(val) * factor
    return None


def _datum(raw: Any, unit: str, *, seconds: bool = False) -> Optional[Datum]:
    """Normalize a mixed bare-float / structured value into a Datum.

    ``seconds`` indicates the logical quantity is a time, so a nested duration
    dict (``{value, unit}``) or bare number is converted to seconds. An
    ``unmeasured`` placeholder whose value is 0 is omitted.
    """
    if raw is None:
        return None

    if not isinstance(raw, dict):
        value = _unit_to_seconds(float(raw), "s") if seconds else float(raw)
        return Datum(value=value, unit=unit)

    inner = raw.get("value")
    if isinstance(inner, dict):
        if inner.get("value") is None:
            return None
        value = _unit_to_seconds(float(inner["value"]), inner.get("unit"))
        orig = float(inner["value"])
        factor = value / orig if orig else 1.0
    elif isinstance(inner, (int, float)) and not isinstance(inner, bool):
        value = _unit_to_seconds(float(inner), "s") if seconds else float(inner)
        factor = 1.0
    else:
        return None

    status = raw.get("calibration_status")
    if status == "unmeasured" and value == 0:
        return None

    kw: dict[str, Any] = {"value": value, "unit": unit}
    em = _error_number(raw.get("err_minus", raw.get("error_minus")), factor)
    ep = _error_number(raw.get("err_plus", raw.get("error_plus")), factor)
    if em is not None and ep is not None:
        kw["err_minus"] = em
        kw["err_plus"] = ep
    if status in _STATUS:
        kw["status"] = status
    updated = raw.get("updated_at") or raw.get("last_calibrated")
    if isinstance(updated, str) and updated:
        kw["updated_at"] = _rfc3339(updated)
    return Datum(**kw)


def _from_qubit_cal(field: Any, comp_field: Any, unit: str) -> Optional[Datum]:
    """Build a datum from a ``qubit_cal`` entry, which is already in SI units.

    A null field is omitted. Status is copied from the matching component when
    that component actually reports a measurement.
    """
    if not isinstance(field, dict) or field.get("value") is None:
        return None
    value = float(field["value"])
    kw: dict[str, Any] = {"value": value, "unit": unit}
    em = _error_number(field.get("error_minus"), 1.0)
    ep = _error_number(field.get("error_plus"), 1.0)
    if em is not None and ep is not None:
        kw["err_minus"] = em
        kw["err_plus"] = ep
    if isinstance(comp_field, dict):
        status = comp_field.get("calibration_status")
        if status in _STATUS and status != "unmeasured":
            kw["status"] = status
    updated = field.get("last_calibrated")
    if not isinstance(updated, str) or not updated:
        updated = comp_field.get("updated_at") if isinstance(comp_field, dict) else None
    if isinstance(updated, str) and updated:
        kw["updated_at"] = _rfc3339(updated)
    return Datum(**kw)


def _max_abs_dev(sums: list[float]) -> float:
    return max((abs(s - 1.0) for s in sums), default=0.0)


def _orient_confusion(cm: list) -> list:
    """Return a row-stochastic confusion matrix.

    Keep the matrix when its rows already sum to 1 at least as closely as its
    columns. Transpose when the columns sum to about 1 and the rows fit worse,
    which is how Boulder Opal stores the matrix.
    """
    if not cm or not isinstance(cm, list) or not isinstance(cm[0], list):
        return cm
    width = len(cm[0])
    if width == 0 or any(not isinstance(row, list) or len(row) != width for row in cm):
        return cm
    row_sums = [float(sum(row)) for row in cm]
    col_sums = [float(sum(row[j] for row in cm)) for j in range(width)]
    row_dev = _max_abs_dev(row_sums)
    col_dev = _max_abs_dev(col_sums)
    if col_dev <= _CM_TOL and col_dev < row_dev:
        return [list(col) for col in zip(*cm)]
    return cm


def _roster(payload: dict) -> tuple[list[str], Optional[dict[str, dict]]]:
    """Full chip order and, when present, the ``qubit_cal`` entries by label.

    ``qubit_cal`` order is the roster. Without it, the roster is the sorted
    union of transmon component labels and ``enabled_qubits``, so the index
    does not shrink to whichever subset is enabled today.
    """
    qc = payload.get("qubit_cal")
    if isinstance(qc, list):
        labels: list[str] = []
        by_label: dict[str, dict] = {}
        for entry in qc:
            if isinstance(entry, dict) and isinstance(entry.get("qubit"), str):
                labels.append(entry["qubit"])
                by_label[entry["qubit"]] = entry
        if labels:
            return labels, by_label

    labels_set: set[str] = set()
    for key, comp in (payload.get("components") or {}).items():
        if isinstance(comp, dict) and comp.get("dtype") == "transmon":
            labels_set.add(key)
    for lab in payload.get("enabled_qubits") or []:
        if isinstance(lab, str):
            labels_set.add(lab)
    return sorted(labels_set), None


def _label_maps(roster: list[str]) -> tuple[dict[str, str], dict[str, str]]:
    """Return (label->$n, $n->label) for a stable roster."""
    label_to_ref: dict[str, str] = {}
    ref_to_label: dict[str, str] = {}
    for i, label in enumerate(roster):
        ref = f"${i}"
        label_to_ref[label] = ref
        ref_to_label[ref] = label
    return label_to_ref, ref_to_label


def _operational_labels(
    payload: dict,
    roster: list[str],
    cal_index: Optional[dict[str, dict]],
) -> list[str]:
    """Labels currently offered for use, in roster order."""
    if cal_index is not None:
        return [
            label
            for label in roster
            if cal_index.get(label, {}).get("operational") is True
        ]
    enabled = {lab for lab in (payload.get("enabled_qubits") or []) if isinstance(lab, str)}
    return [label for label in roster if label in enabled]


def _build_qubit(
    comp: dict,
    classifier: Optional[dict],
    cal_entry: Optional[dict],
) -> QubitProperties:
    qp = QubitProperties()
    for cal_key, comp_key, attr, unit, seconds in _QUBIT_FIELDS:
        comp_field = comp.get(comp_key)
        if cal_entry is not None:
            # An explicit null in qubit_cal means "no measurement", not "fall
            # back to the component tree", which stores unmeasured as 0.
            datum = _from_qubit_cal(cal_entry.get(cal_key), comp_field, unit)
        else:
            datum = _datum(comp_field, unit, seconds=seconds)
        if datum is not None:
            setattr(qp, attr, datum)

    if classifier:
        ro = Readout()
        cm = classifier.get("confusion_matrix")
        if cm:
            oriented = _orient_confusion(cm)
            ro.confusion_matrix = oriented
            diag = [oriented[i][i] for i in range(len(oriented))]
            fidelity = sum(diag) / len(diag)
            ro.fidelity = Datum(
                value=fidelity,
                unit="dimensionless",
                method="confusion_matrix_diagonal",
                metric="readout_fidelity",
            )
        ro.classifier = Classifier(
            type="linear_iq",
            projection=classifier.get("projection"),
            threshold=classifier.get("threshold"),
            status=classifier.get("status"),
        )
        qp.readout = ro

    return qp


def _coupling_map(pairs: set[tuple[int, int]]) -> list[list[str]]:
    """Emit DIRECTED coupling-map pairs (both directions) from undirected pairs,
    sorted numerically by ``(i, j)``."""
    directed: set[tuple[int, int]] = set()
    for i, j in pairs:
        directed.add((i, j))
        directed.add((j, i))
    return [[f"${i}", f"${j}"] for i, j in sorted(directed)]


def _ref_index(ref: str) -> int:
    return int(ref[1:])  # "$n" -> n


def _drive_hz(
    label: str,
    components: dict,
    cal_index: Optional[dict[str, dict]],
) -> Optional[float]:
    """Qubit drive frequency. Prefer ``qubit_cal.frequency``, else ``freq_01``."""
    if cal_index is not None:
        freq = (cal_index.get(label) or {}).get("frequency")
        if isinstance(freq, dict) and isinstance(freq.get("value"), (int, float)):
            return float(freq["value"])
    datum = _datum((components.get(label) or {}).get("freq_01"), "Hz")
    return None if datum is None else datum.value


def _same_hz(a: float, b: float) -> bool:
    return math.isclose(a, b, rel_tol=1e-9, abs_tol=1.0)


def _build_defcal(
    key: str,
    params: dict,
    label_to_ref: dict[str, str],
    *,
    drive_hz: Optional[float] = None,
    measure_hz: Optional[float] = None,
) -> Optional[Defcal]:
    # key form: "x:qA1" or "cz:qA1_qA3"
    if ":" not in key:
        return None
    gate_raw, addr = key.split(":", 1)
    gate = _GATE_NAME.get(gate_raw.lower(), gate_raw.lower())
    labels = addr.split("_")
    qubits: list[str] = []
    for lab in labels:
        ref = label_to_ref.get(lab)
        if ref is None:
            return None  # addresses a qubit outside the roster: skip for core
        qubits.append(ref)

    p: dict[str, Any] = {}
    if "duration" in params:
        p["duration_s"] = float(params["duration"])
    if "amp" in params:
        p["amp"] = float(params["amp"])
    if "motzoi" in params:
        p["motzoi"] = float(params["motzoi"])
    if "frequency" in params:
        frequency = float(params["frequency"])
        # x/sx on this stack store the readout tone in `frequency` when it
        # matches the measure defcal. The drive is freq_01 / qubit_cal.frequency.
        # The OpenQASM program string is kept below and is not parsed.
        if (
            gate in ("x", "sx")
            and drive_hz is not None
            and measure_hz is not None
            and _same_hz(frequency, measure_hz)
        ):
            frequency = drive_hz
        p["frequency_hz"] = frequency
    if "integration_time" in params:
        p["integration_time_s"] = float(params["integration_time"])
    # Preserve any other scalar params verbatim (e.g. "role", "program").
    for k, v in params.items():
        if k not in ("duration", "amp", "motzoi", "frequency", "integration_time"):
            p[k] = v

    return Defcal(gate=gate, qubits=qubits, params=p or None)


def from_boulder_opal(
    payload: dict,
    *,
    device_id: Optional[str] = None,
    vendor: Optional[str] = None,
    model: Optional[str] = None,
    captured_at: Optional[str] = None,
    snapshot_id: Optional[str] = None,
) -> OqCalDocument:
    """Convert a Boulder Opal calibration snapshot to a :class:`OqCalDocument`.

    ``device_id``, ``vendor``, ``model``, ``captured_at`` and ``snapshot_id`` are
    optional identity / provenance overrides: a supplied value OVERRIDES the
    source-derived value, an omitted one leaves current behavior. ``device_id``
    is ``qpu_model`` when the source has one, and ``"boulder-opal-device"`` only
    when neither the caller nor the source supplies an id. ``vendor`` is left
    empty unless the caller passes it: the snapshot names the chip, not the
    control-software vendor.
    """
    roster, cal_index = _roster(payload)
    label_to_ref, ref_to_label = _label_maps(roster)
    operational = _operational_labels(payload, roster, cal_index)

    components = payload.get("components") or {}
    classifiers = payload.get("classifiers") or {}

    # Every roster qubit that has a real measurement or a classifier. Disabled
    # qubits stay in the address space; they are listed in qubit_labels and
    # omitted from enabled_qubits. Resonators and ports stay in extensions.
    qubits: dict[str, QubitProperties] = {}
    for label in roster:
        ref = label_to_ref[label]
        comp = components.get(label) or {}
        if comp and comp.get("dtype") not in (None, "transmon"):
            continue
        cal_entry = None if cal_index is None else cal_index.get(label)
        qp = _build_qubit(comp, classifiers.get(label), cal_entry)
        if qp.model_dump(exclude_none=True):
            qubits[ref] = qp

    # defcals
    defcal_src = payload.get("defcals") or {}
    defcals: list[Defcal] = []
    pair_evidence: set[tuple[int, int]] = set()
    for key, params in defcal_src.items():
        if not isinstance(params, dict) or ":" not in key:
            continue
        _gate_raw, addr = key.split(":", 1)
        labels = addr.split("_")
        drive_hz = None
        measure_hz = None
        if len(labels) == 1:
            drive_hz = _drive_hz(labels[0], components, cal_index)
            measure = defcal_src.get(f"measure:{labels[0]}")
            if isinstance(measure, dict) and isinstance(measure.get("frequency"), (int, float)):
                measure_hz = float(measure["frequency"])
        dc = _build_defcal(
            key,
            params,
            label_to_ref,
            drive_hz=drive_hz,
            measure_hz=measure_hz,
        )
        if dc is not None:
            defcals.append(dc)
            if len(dc.qubits) == 2:
                pair_evidence.add(
                    (_ref_index(dc.qubits[0]), _ref_index(dc.qubits[1]))
                )

    # gates from gate_errors
    gates: list[GateEntry] = []
    for ge in payload.get("gate_errors") or []:
        labels = ge.get("qubits") or []
        refs: list[str] = []
        ok = True
        for lab in labels:
            ref = label_to_ref.get(lab)
            if ref is None:
                ok = False
                break
            refs.append(ref)
        if not ok or not refs:
            continue
        gate_raw = ge.get("gate", "")
        name = _GATE_NAME.get(gate_raw.lower(), gate_raw.lower())
        kw: dict[str, Any] = {}
        if ge.get("calibration_status") in _STATUS:
            kw["status"] = ge["calibration_status"]
        if ge.get("updated_at"):
            kw["updated_at"] = ge["updated_at"]
        error = Datum(value=float(ge["value"]), unit="dimensionless", **kw)
        gates.append(GateEntry(name=name, qubits=refs, error=error))
        if len(refs) == 2:
            pair_evidence.add((_ref_index(refs[0]), _ref_index(refs[1])))

    source_model = payload.get("qpu_model")
    device = Device(
        id=source_model if isinstance(source_model, str) and source_model else "boulder-opal-device",
        num_qubits=len(roster),
    )
    if isinstance(source_model, str) and source_model:
        device.model = source_model
    if ref_to_label:
        device.qubit_labels = ref_to_label
        device.enabled_qubits = [label_to_ref[label] for label in operational]
    if pair_evidence:
        device.coupling_map = _coupling_map(pair_evidence)

    snapshot = Snapshot(source="boulder-opal", source_schema="boulder-opal-snapshot")
    if isinstance(payload.get("version"), str) and payload["version"]:
        snapshot.captured_at = _rfc3339(payload["version"])

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
        extensions={"boulder_opal": payload},
    )
    if qubits:
        doc.qubits = qubits
    if gates:
        doc.gates = gates
    if defcals:
        doc.defcals = defcals
    return doc


register_importer("boulder-opal", from_boulder_opal)
