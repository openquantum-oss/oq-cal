"""Calibration drift engine: compare two oq-cal documents datum-by-datum.

``diff(a, b)`` returns a :class:`OqCalDiff` describing how every datum-bearing
value moved between two snapshots of the same (or comparable) device. It is the
basis for ``oq-cal diff`` drift reports.

What is compared
----------------
Every numeric leaf that oq-cal treats as a measured quantity:

* ``aggregates``: qubits/readout/1q/2q gate metrics and ``ops`` durations;
* ``qubits.$n``: t1/t2/t2_echo/frequency_01/anharmonicity, readout fidelity and
  duration, and benchmark fidelity/error;
* ``gates[name@qubits]``: fidelity/error/duration and benchmark fidelity/error;
* ``defcals[gate@qubits]``: numeric ``params`` entries (compared numerically);
* datum ``status``, ``method``, and ``metric`` strings, at ``<path>.status``,
  ``<path>.method``, and ``<path>.metric``, only when the two strings differ.

Gates and defcals are keyed by ``name@$a,$b`` so that reordering between the two
documents does not create spurious add/remove churn. A string change is ``major``
and carries ``a_status`` / ``b_status`` instead of numeric values. The path suffix
says which string moved. It does not outrank a value change in
:meth:`OqCalDiff.worst_offenders`.

Significance
------------
Each entry is classified by relative change (or appearance/disappearance):

* ``major``: a datum appeared or disappeared, or ``|rel_change| > MAJOR_REL``;
* ``minor``: ``|rel_change| > MINOR_REL``;
* ``noise``: otherwise.

Thresholds are module-level constants (:data:`MAJOR_REL`, :data:`MINOR_REL`).
When the baseline value is zero, relative change is undefined; such entries are
treated as ``major`` if the absolute change is non-zero (otherwise ``noise``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from .models import OqCalDocument

MAJOR_REL = 0.20
MINOR_REL = 0.05

_APPEARED = "<appeared>"
_DISAPPEARED = "<disappeared>"


@dataclass(frozen=True)
class DiffEntry:
    """A single changed (or added/removed) datum."""

    path: str
    a_value: Optional[float]
    b_value: Optional[float]
    abs_change: Optional[float]
    rel_change: Optional[float]
    significance: str  # "major" | "minor" | "noise"
    a_status: Optional[str] = None
    b_status: Optional[str] = None


@dataclass
class OqCalDiff:
    """The result of comparing two documents."""

    entries: list[DiffEntry] = field(default_factory=list)

    @property
    def counts(self) -> dict[str, int]:
        """Count of entries by significance."""
        out = {"major": 0, "minor": 0, "noise": 0}
        for e in self.entries:
            out[e.significance] += 1
        return out

    def worst_offenders(self, n: int = 5) -> list[DiffEntry]:
        """Top ``n`` entries by magnitude of relative change (appear/disappear first)."""

        def key(e: DiffEntry):
            # Appear/disappear (rel_change None but significance major) sort first.
            # Status entries are not numeric; rank them after value changes.
            if e.a_status is not None or e.b_status is not None:
                return 0.0
            rel = abs(e.rel_change) if e.rel_change is not None else float("inf")
            return rel

        return sorted(self.entries, key=key, reverse=True)[:n]

    def summary(self) -> dict[str, Any]:
        """Machine-readable summary: counts + worst offenders."""
        return {
            "counts": self.counts,
            "total": len(self.entries),
            "worst_offenders": [
                {
                    "path": e.path,
                    "a_value": e.a_value,
                    "b_value": e.b_value,
                    "rel_change": e.rel_change,
                    "significance": e.significance,
                    "a_status": e.a_status,
                    "b_status": e.b_status,
                }
                for e in self.worst_offenders()
            ],
        }


def _classify(a: Optional[float], b: Optional[float]) -> DiffEntry:
    """Build a classified entry for a single path from two (possibly None) values."""
    appeared = a is None and b is not None
    disappeared = a is not None and b is None

    if appeared or disappeared:
        return DiffEntry(
            path="",  # filled by caller
            a_value=a,
            b_value=b,
            abs_change=None,
            rel_change=None,
            significance="major",
        )

    # Both present.
    assert a is not None and b is not None
    abs_change = b - a
    if a == 0:
        rel_change = None
        significance = "major" if abs_change != 0 else "noise"
    else:
        rel_change = abs_change / a
        mag = abs(rel_change)
        if mag > MAJOR_REL:
            significance = "major"
        elif mag > MINOR_REL:
            significance = "minor"
        else:
            significance = "noise"
    return DiffEntry(
        path="",
        a_value=a,
        b_value=b,
        abs_change=abs_change,
        rel_change=rel_change,
        significance=significance,
    )


def _entry(path: str, a: Optional[float], b: Optional[float]) -> Optional[DiffEntry]:
    """Classified entry for ``path``; ``None`` when both sides are absent."""
    if a is None and b is None:
        return None
    base = _classify(a, b)
    return DiffEntry(
        path=path,
        a_value=base.a_value,
        b_value=base.b_value,
        abs_change=base.abs_change,
        rel_change=base.rel_change,
        significance=base.significance,
    )


def _datum_value(datum) -> Optional[float]:
    return None if datum is None else getattr(datum, "value", None)


_LABELS = ("status", "method", "metric")


def _datum_label(datum, field: str) -> Optional[str]:
    if datum is None:
        return None
    value = getattr(datum, field, None)
    return value if isinstance(value, str) and value else None


def _collect_scalars(doc: OqCalDocument) -> dict[str, float]:
    """Flatten a document into {path: value} over every datum-bearing path."""
    out: dict[str, float] = {}

    def put(path: str, value: Optional[float]) -> None:
        if value is not None:
            out[path] = value

    # --- aggregates ---
    agg = doc.aggregates
    if agg is not None:
        if agg.qubits is not None:
            put("aggregates.qubits.t1", _datum_value(agg.qubits.t1))
            put("aggregates.qubits.t2", _datum_value(agg.qubits.t2))
            put("aggregates.qubits.t2_echo", _datum_value(agg.qubits.t2_echo))
        if agg.readout is not None:
            put("aggregates.readout.fidelity", _datum_value(agg.readout.fidelity))
            put("aggregates.readout.duration", _datum_value(agg.readout.duration))
        for gname in ("gates_1q", "gates_2q"):
            g = getattr(agg, gname)
            if g is not None:
                put(f"aggregates.{gname}.fidelity", _datum_value(g.fidelity))
                put(f"aggregates.{gname}.error", _datum_value(g.error))
                put(f"aggregates.{gname}.duration", _datum_value(g.duration))
        for op, datum in (agg.ops or {}).items():
            put(f"aggregates.ops.{op}", _datum_value(datum))

    # --- qubits ---
    for ref, props in (doc.qubits or {}).items():
        base = f"qubits.{ref}"
        put(f"{base}.t1", _datum_value(props.t1))
        put(f"{base}.t2", _datum_value(props.t2))
        put(f"{base}.t2_echo", _datum_value(props.t2_echo))
        put(f"{base}.frequency_01", _datum_value(props.frequency_01))
        put(f"{base}.anharmonicity", _datum_value(props.anharmonicity))
        if props.readout is not None:
            put(f"{base}.readout.fidelity", _datum_value(props.readout.fidelity))
            put(f"{base}.readout.duration", _datum_value(props.readout.duration))
            cm = props.readout.confusion_matrix
            if cm:
                for i, row in enumerate(cm):
                    for j, v in enumerate(row):
                        put(f"{base}.readout.confusion_matrix.{i}.{j}", float(v))
        for k, bench in enumerate(props.benchmarks or []):
            bp = f"{base}.benchmarks.{bench.protocol}"
            put(f"{bp}.fidelity", _datum_value(bench.fidelity))
            put(f"{bp}.error", _datum_value(bench.error))

    # --- gates (keyed by name@qubits so order does not matter) ---
    for entry in doc.gates or []:
        key = f"{entry.name}@{','.join(entry.qubits)}"
        base = f"gates.{key}"
        put(f"{base}.fidelity", _datum_value(entry.fidelity))
        put(f"{base}.error", _datum_value(entry.error))
        put(f"{base}.duration", _datum_value(entry.duration))
        for bench in entry.benchmarks or []:
            bp = f"{base}.benchmarks.{bench.protocol}"
            put(f"{bp}.fidelity", _datum_value(bench.fidelity))
            put(f"{bp}.error", _datum_value(bench.error))

    # --- defcals (numeric params only, keyed by gate@qubits) ---
    for entry in doc.defcals or []:
        key = f"{entry.gate}@{','.join(entry.qubits)}"
        base = f"defcals.{key}.params"
        for pk, pv in (entry.params or {}).items():
            if isinstance(pv, bool):
                continue
            if isinstance(pv, (int, float)):
                put(f"{base}.{pk}", float(pv))

    return out


def _collect_labels(doc: OqCalDocument) -> dict[str, str]:
    """Flatten datum status, method, and metric strings.

    Only datums are visited. Confusion-matrix cells and defcal params have none
    of these labels. An absent label is omitted so an unchanged document stays
    quiet. A change of metric or method is a change of what the number means,
    so it is reported even when the numeric value is unchanged.
    """
    out: dict[str, str] = {}

    def put(path: str, datum) -> None:
        for field in _LABELS:
            label = _datum_label(datum, field)
            if label is not None:
                out[f"{path}.{field}"] = label

    agg = doc.aggregates
    if agg is not None:
        if agg.qubits is not None:
            put("aggregates.qubits.t1", agg.qubits.t1)
            put("aggregates.qubits.t2", agg.qubits.t2)
            put("aggregates.qubits.t2_echo", agg.qubits.t2_echo)
        if agg.readout is not None:
            put("aggregates.readout.fidelity", agg.readout.fidelity)
            put("aggregates.readout.duration", agg.readout.duration)
        for gname in ("gates_1q", "gates_2q"):
            g = getattr(agg, gname)
            if g is not None:
                put(f"aggregates.{gname}.fidelity", g.fidelity)
                put(f"aggregates.{gname}.error", g.error)
                put(f"aggregates.{gname}.duration", g.duration)
        for op, datum in (agg.ops or {}).items():
            put(f"aggregates.ops.{op}", datum)

    for ref, props in (doc.qubits or {}).items():
        base = f"qubits.{ref}"
        put(f"{base}.t1", props.t1)
        put(f"{base}.t2", props.t2)
        put(f"{base}.t2_echo", props.t2_echo)
        put(f"{base}.frequency_01", props.frequency_01)
        put(f"{base}.anharmonicity", props.anharmonicity)
        if props.readout is not None:
            put(f"{base}.readout.fidelity", props.readout.fidelity)
            put(f"{base}.readout.duration", props.readout.duration)
        for bench in props.benchmarks or []:
            bp = f"{base}.benchmarks.{bench.protocol}"
            put(f"{bp}.fidelity", bench.fidelity)
            put(f"{bp}.error", bench.error)

    for entry in doc.gates or []:
        key = f"{entry.name}@{','.join(entry.qubits)}"
        base = f"gates.{key}"
        put(f"{base}.fidelity", entry.fidelity)
        put(f"{base}.error", entry.error)
        put(f"{base}.duration", entry.duration)
        for bench in entry.benchmarks or []:
            bp = f"{base}.benchmarks.{bench.protocol}"
            put(f"{bp}.fidelity", bench.fidelity)
            put(f"{bp}.error", bench.error)

    return out


def _status_entry(path: str, a: Optional[str], b: Optional[str]) -> Optional[DiffEntry]:
    """Major entry when two status strings differ. Equal strings emit nothing."""
    if a == b:
        return None
    return DiffEntry(
        path=path,
        a_value=None,
        b_value=None,
        abs_change=None,
        rel_change=None,
        significance="major",
        a_status=a,
        b_status=b,
    )


def diff(a: OqCalDocument, b: OqCalDocument) -> OqCalDiff:
    """Compare two documents and return a :class:`OqCalDiff`."""
    sa = _collect_scalars(a)
    sb = _collect_scalars(b)
    status_a = _collect_labels(a)
    status_b = _collect_labels(b)
    result = OqCalDiff()
    for path in sorted(set(sa) | set(sb)):
        entry = _entry(path, sa.get(path), sb.get(path))
        if entry is not None:
            result.entries.append(entry)
    for path in sorted(set(status_a) | set(status_b)):
        entry = _status_entry(path, status_a.get(path), status_b.get(path))
        if entry is not None:
            result.entries.append(entry)
    result.entries.sort(key=lambda e: e.path)
    return result
