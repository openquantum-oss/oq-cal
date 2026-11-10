"""Tests for schema + semantic validation."""

from __future__ import annotations

import json

from pathlib import Path

from oq_cal import OqCalDocument, validate
from oq_cal.validate import ValidationIssue


def _errors(issues):
    return [i for i in issues if i.severity == "error"]


def test_load_schema_falls_back_to_repo_spec(monkeypatch):
    """The packaged schema is preferred. If it is missing, use the repo spec.

    ``validate.py`` lives at ``python/src/oq_cal/``, so the repository root is
    ``parents[3]``. ``parents[2]`` is ``python/`` and has no ``spec/schema``.
    """
    import importlib

    validate_mod = importlib.import_module("oq_cal.validate")
    validate_mod.load_schema.cache_clear()

    def missing(_package):
        raise FileNotFoundError("packaged schema missing")

    monkeypatch.setattr(validate_mod.resources, "files", missing)
    schema = validate_mod.load_schema()
    assert schema["title"] == "oq-cal device calibration document"
    assert "metric" in schema["$defs"]["datum"]["properties"]
    repo = Path(validate_mod.__file__).resolve().parents[3] / "spec" / "schema" / "oq-cal-0.1.schema.json"
    assert repo.is_file()
    validate_mod.load_schema.cache_clear()


def test_unknown_metric_string_is_valid():
    data = {
        "oq-cal": {"name": "oq-cal.device_calibration", "version": "0.1"},
        "device": {"id": "x", "num_qubits": 1},
        "snapshot": {"source": "test"},
        "qubits": {
            "$0": {
                "t1": {"value": 1e-5, "unit": "s", "metric": "not_a_closed_enum"},
            }
        },
    }
    assert validate(data) == []


def test_valid_fixtures_validate_clean(oq_cal_valid_file):
    data = json.loads(oq_cal_valid_file.read_text())
    issues = validate(data)
    assert issues == [], f"unexpected issues in {oq_cal_valid_file.name}: {issues}"


def test_validate_accepts_model_instance(fixtures_dir):
    doc = OqCalDocument.model_validate_json(
        (fixtures_dir / "oq-cal-docs" / "valid_per_qubit.json").read_text()
    )
    assert validate(doc) == []


def test_missing_header_is_error(fixtures_dir):
    data = json.loads((fixtures_dir / "oq-cal-docs" / "invalid_missing_header.json").read_text())
    issues = validate(data)
    errs = _errors(issues)
    assert errs, "expected a schema error for the missing oq-cal header"
    assert any("oq-cal" in e.message or e.path == "<root>" for e in errs)


def test_non_si_unit_is_error(fixtures_dir):
    data = json.loads((fixtures_dir / "oq-cal-docs" / "invalid_non_si_unit.json").read_text())
    issues = validate(data)
    errs = _errors(issues)
    messages = " ".join(e.message for e in errs)
    assert "ns" in messages or "GHz" in messages
    # both the schema enum and the semantic check should flag it; at least one must.
    assert any("unit" in e.path or "ns" in e.message or "GHz" in e.message for e in errs)


def test_qubit_ref_out_of_range():
    data = {
        "oq-cal": {"name": "oq-cal.device_calibration", "version": "0.1"},
        "device": {"id": "x", "num_qubits": 2},
        "snapshot": {"source": "test"},
        "qubits": {"$5": {"t1": {"value": 1e-5, "unit": "s"}}},
    }
    errs = _errors(validate(data))
    assert any("out of range" in e.message for e in errs)


def test_std_error_with_asymmetric_is_error():
    data = {
        "oq-cal": {"name": "oq-cal.device_calibration", "version": "0.1"},
        "device": {"id": "x", "num_qubits": 1},
        "snapshot": {"source": "test"},
        "qubits": {"$0": {"t1": {"value": 1e-5, "unit": "s", "std_error": 1e-7, "err_minus": 1e-7, "err_plus": 1e-7}}},
    }
    errs = _errors(validate(data))
    assert any("std_error" in e.message for e in errs)


def test_unpaired_err_is_error():
    data = {
        "oq-cal": {"name": "oq-cal.device_calibration", "version": "0.1"},
        "device": {"id": "x", "num_qubits": 1},
        "snapshot": {"source": "test"},
        "qubits": {"$0": {"t1": {"value": 1e-5, "unit": "s", "err_minus": 1e-7}}},
    }
    errs = _errors(validate(data))
    assert any("err_minus and err_plus" in e.message for e in errs)


def test_confusion_matrix_row_sum():
    data = {
        "oq-cal": {"name": "oq-cal.device_calibration", "version": "0.1"},
        "device": {"id": "x", "num_qubits": 1},
        "snapshot": {"source": "test"},
        "qubits": {"$0": {"readout": {"confusion_matrix": [[0.9, 0.3], [0.1, 0.9]]}}},
    }
    errs = _errors(validate(data))
    assert any("confusion-matrix row" in e.message for e in errs)


def test_good_confusion_matrix_passes():
    data = {
        "oq-cal": {"name": "oq-cal.device_calibration", "version": "0.1"},
        "device": {"id": "x", "num_qubits": 1},
        "snapshot": {"source": "test"},
        "qubits": {"$0": {"readout": {"confusion_matrix": [[0.96, 0.04], [0.07, 0.93]]}}},
    }
    assert _errors(validate(data)) == []


def test_extensions_are_not_unit_checked():
    # A non-SI unit buried in extensions (verbatim source) must NOT be flagged.
    data = {
        "oq-cal": {"name": "oq-cal.device_calibration", "version": "0.1"},
        "device": {"id": "x", "num_qubits": 1},
        "snapshot": {"source": "test"},
        "extensions": {"raw": {"t1": {"value": 18220, "unit": "ns"}}},
    }
    assert _errors(validate(data)) == []


def test_issue_str():
    issue = ValidationIssue("error", "qubits/$0", "boom")
    assert "error" in str(issue) and "boom" in str(issue)
