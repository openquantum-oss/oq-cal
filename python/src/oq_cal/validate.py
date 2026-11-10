"""Validation for oq-cal documents: JSON-Schema plus semantic checks.

``validate(doc_or_dict)`` returns a list of :class:`ValidationIssue`. An empty
list means the document is valid. Issues carry a severity (``error`` or
``warning``), a dotted path into the document, and a human-readable message.

The semantic layer enforces rules the JSON Schema cannot express cleanly:
  * units are SI-canonical (``s``, ``Hz``, ``dimensionless``);
  * ``$n`` qubit references stay within ``device.num_qubits``;
  * confusion-matrix rows sum to ~1;
  * ``err_minus``/``err_plus`` are paired;
  * ``std_error`` never appears alongside ``err_minus``/``err_plus``.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import Any, Union

import jsonschema

from .models import OqCalDocument

_QUBIT_RE = re.compile(r"^\$([0-9]+)$")
_SI_UNITS = {"s", "Hz", "dimensionless"}
_CM_ROW_TOLERANCE = 0.02


@dataclass(frozen=True)
class ValidationIssue:
    """A single validation finding."""

    severity: str  # "error" | "warning"
    path: str
    message: str

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        return f"[{self.severity}] {self.path}: {self.message}"


@lru_cache(maxsize=1)
def load_schema() -> dict[str, Any]:
    """Load the bundled oq-cal JSON Schema."""
    # Prefer the packaged copy (installed wheel); fall back to the repo tree.
    try:
        ref = resources.files("oq_cal").joinpath("_schema/oq-cal-0.1.schema.json")
        return json.loads(ref.read_text(encoding="utf-8"))
    except (FileNotFoundError, ModuleNotFoundError, AttributeError):
        pass
    # validate.py lives at python/src/oq_cal/validate.py, so parents[3] is the
    # repository root. parents[2] is python/ and does not contain spec/.
    repo_schema = (
        Path(__file__).resolve().parents[3] / "spec" / "schema" / "oq-cal-0.1.schema.json"
    )
    return json.loads(repo_schema.read_text(encoding="utf-8"))


def _as_dict(doc_or_dict: Union[OqCalDocument, dict, str, bytes]) -> dict[str, Any]:
    if isinstance(doc_or_dict, OqCalDocument):
        return doc_or_dict.model_dump(mode="json", exclude_none=True)
    if isinstance(doc_or_dict, (str, bytes)):
        return json.loads(doc_or_dict)
    if isinstance(doc_or_dict, dict):
        return doc_or_dict
    raise TypeError(f"cannot validate object of type {type(doc_or_dict)!r}")


def validate(doc_or_dict: Union[OqCalDocument, dict, str, bytes]) -> list[ValidationIssue]:
    """Validate an oq-cal document, returning a list of issues (empty == valid)."""
    data = _as_dict(doc_or_dict)
    issues: list[ValidationIssue] = []
    issues.extend(_schema_issues(data))
    issues.extend(_semantic_issues(data))
    return issues


# ---------------------------------------------------------------------------
# Schema layer
# ---------------------------------------------------------------------------


def _schema_issues(data: dict[str, Any]) -> list[ValidationIssue]:
    schema = load_schema()
    validator = jsonschema.Draft202012Validator(schema)
    issues: list[ValidationIssue] = []
    for err in sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path)):
        path = "/".join(str(p) for p in err.absolute_path) or "<root>"
        issues.append(ValidationIssue("error", path, err.message))
    return issues


# ---------------------------------------------------------------------------
# Semantic layer
# ---------------------------------------------------------------------------


def _semantic_issues(data: dict[str, Any]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    num_qubits = None
    device = data.get("device")
    if isinstance(device, dict):
        num_qubits = device.get("num_qubits")

    # Walk every datum anywhere in the tree: units + err pairing + std_error clash.
    for path, datum in _iter_datums(data):
        _check_datum(path, datum, issues)

    # Qubit reference bounds.
    for path, ref in _iter_qubit_refs(data):
        m = _QUBIT_RE.match(ref)
        if not m:
            issues.append(
                ValidationIssue("error", path, f"malformed qubit reference {ref!r} (expected $n)")
            )
            continue
        if isinstance(num_qubits, int) and int(m.group(1)) >= num_qubits:
            issues.append(
                ValidationIssue(
                    "error",
                    path,
                    f"qubit reference {ref} out of range (num_qubits={num_qubits})",
                )
            )

    # Confusion-matrix rows sum to ~1.
    for path, matrix in _iter_confusion_matrices(data):
        for i, row in enumerate(matrix):
            try:
                total = sum(float(x) for x in row)
            except (TypeError, ValueError):
                issues.append(ValidationIssue("error", f"{path}/{i}", "non-numeric confusion-matrix entry"))
                continue
            if abs(total - 1.0) > _CM_ROW_TOLERANCE:
                issues.append(
                    ValidationIssue(
                        "error",
                        f"{path}/{i}",
                        f"confusion-matrix row sums to {total:.4f}, expected ~1",
                    )
                )
    return issues


def _check_datum(path: str, datum: dict[str, Any], issues: list[ValidationIssue]) -> None:
    unit = datum.get("unit")
    if unit is not None and unit not in _SI_UNITS:
        issues.append(
            ValidationIssue(
                "error",
                f"{path}/unit",
                f"non-SI unit {unit!r} (allowed: {sorted(_SI_UNITS)})",
            )
        )
    has_std = datum.get("std_error") is not None
    has_minus = datum.get("err_minus") is not None
    has_plus = datum.get("err_plus") is not None
    if has_std and (has_minus or has_plus):
        issues.append(
            ValidationIssue(
                "error",
                path,
                "std_error must not appear together with err_minus/err_plus",
            )
        )
    if has_minus != has_plus:
        issues.append(
            ValidationIssue(
                "error",
                path,
                "err_minus and err_plus must be provided together",
            )
        )


# ---------------------------------------------------------------------------
# Tree walkers
# ---------------------------------------------------------------------------


def _is_datum(obj: Any) -> bool:
    return isinstance(obj, dict) and "value" in obj and "unit" in obj


def _iter_datums(data: dict[str, Any]):
    """Yield (path, datum) for every datum-shaped dict in the document.

    Excludes the ``extensions`` subtree (verbatim source payloads).
    """

    def walk(node: Any, path: str):
        if isinstance(node, dict):
            if _is_datum(node):
                yield path, node
            for k, v in node.items():
                if path == "" and k == "extensions":
                    continue
                yield from walk(v, f"{path}/{k}" if path else k)
        elif isinstance(node, list):
            for i, v in enumerate(node):
                yield from walk(v, f"{path}/{i}")

    yield from walk(data, "")


def _iter_qubit_refs(data: dict[str, Any]):
    """Yield (path, ref) for qubit references in structural positions."""
    device = data.get("device", {})
    if isinstance(device, dict):
        for key in device.get("qubit_labels", {}) or {}:
            yield f"device/qubit_labels/{key}", key
        for i, ref in enumerate(device.get("enabled_qubits", []) or []):
            yield f"device/enabled_qubits/{i}", ref
        for i, pair in enumerate(device.get("coupling_map", []) or []):
            for j, ref in enumerate(pair or []):
                yield f"device/coupling_map/{i}/{j}", ref

    qubits = data.get("qubits")
    if isinstance(qubits, dict):
        for key in qubits:
            yield f"qubits/{key}", key

    for section in ("gates", "defcals"):
        entries = data.get(section)
        if isinstance(entries, list):
            for i, entry in enumerate(entries):
                if isinstance(entry, dict):
                    for j, ref in enumerate(entry.get("qubits", []) or []):
                        yield f"{section}/{i}/qubits/{j}", ref


def _iter_confusion_matrices(data: dict[str, Any]):
    qubits = data.get("qubits")
    if isinstance(qubits, dict):
        for key, props in qubits.items():
            if isinstance(props, dict):
                ro = props.get("readout")
                if isinstance(ro, dict) and isinstance(ro.get("confusion_matrix"), list):
                    yield f"qubits/{key}/readout/confusion_matrix", ro["confusion_matrix"]
