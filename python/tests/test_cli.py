"""Tests for the oq-cal CLI (click CliRunner)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from oq_cal import registry
from oq_cal.cli import main
from oq_cal.models import (
    Datum,
    Device,
    Header,
    OqCalDocument,
    QubitProperties,
    Snapshot,
    Unit,
)

_FIXTURES_ROOT = Path(__file__).resolve().parents[2] / "fixtures"
FIXTURES = _FIXTURES_ROOT / "oq-cal-docs"


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------


def test_validate_valid(runner):
    r = runner.invoke(main, ["validate", str(FIXTURES / "valid_per_qubit.json")])
    assert r.exit_code == 0
    assert "OK" in r.output


def test_validate_invalid(runner):
    r = runner.invoke(main, ["validate", str(FIXTURES / "invalid_non_si_unit.json")])
    assert r.exit_code == 1
    assert "INVALID" in r.output


# ---------------------------------------------------------------------------
# convert
# ---------------------------------------------------------------------------


def test_convert_oq_cal_to_oq_cal_stdout(runner):
    r = runner.invoke(
        main,
        ["convert", str(FIXTURES / "valid_per_qubit.json"), "--from", "oq-cal", "--to", "oq-cal"],
    )
    assert r.exit_code == 0, r.output
    parsed = json.loads(r.output)
    assert parsed["oq-cal"]["version"] == "0.1"


def test_convert_to_file(runner, tmp_path):
    out = tmp_path / "out.json"
    r = runner.invoke(
        main,
        ["convert", str(FIXTURES / "valid_per_qubit.json"), "-o", str(out)],
    )
    assert r.exit_code == 0, r.output
    assert out.exists()
    assert json.loads(out.read_text())["device"]["num_qubits"] == 8


def test_convert_with_stub_importer_and_exporter(runner, tmp_path):
    """Register stub converters directly, independent of the real importers."""

    def stub_importer(data: dict) -> OqCalDocument:
        return OqCalDocument(
            oq_cal=Header(version="0.1"),
            device=Device(id=data["id"], num_qubits=data["n"]),
            snapshot=Snapshot(source="stub", captured_at="2026-10-31T00:00:00Z"),
            qubits={"$0": QubitProperties(t1=Datum(value=1e-5, unit=Unit.SECOND))},
        )

    def stub_exporter(doc: OqCalDocument) -> dict:
        return {"device_id": doc.device.id, "num_qubits": doc.device.num_qubits}

    registry.register_importer("stubfmt", stub_importer)
    registry.register_exporter("stubout", stub_exporter)

    src = tmp_path / "src.json"
    src.write_text(json.dumps({"id": "stub:dev", "n": 3}))

    r = runner.invoke(
        main, ["convert", str(src), "--from", "stubfmt", "--to", "stubout"]
    )
    assert r.exit_code == 0, r.output
    parsed = json.loads(r.output)
    assert parsed == {"device_id": "stub:dev", "num_qubits": 3}


def test_convert_stub_importer_to_oq_cal(runner, tmp_path):
    def stub_importer(data: dict) -> OqCalDocument:
        return OqCalDocument(
            oq_cal=Header(version="0.1"),
            device=Device(id="stub:x", num_qubits=1),
            snapshot=Snapshot(source="stub", captured_at="2026-10-31T00:00:00Z"),
        )

    registry.register_importer("stubfmt2", stub_importer)
    src = tmp_path / "src.json"
    src.write_text("{}")
    r = runner.invoke(main, ["convert", str(src), "--from", "stubfmt2", "--to", "oq-cal"])
    assert r.exit_code == 0, r.output
    assert json.loads(r.output)["device"]["id"] == "stub:x"


def test_convert_opt_forwarded_to_importer_and_filtered(runner, tmp_path):
    """--opt values are coerced and forwarded, filtered per-callable signature."""
    captured_imp: dict = {}
    captured_exp: dict = {}

    def stub_importer(data: dict, *, num_qubits: int = 1, vendor: str = "?") -> OqCalDocument:
        captured_imp["num_qubits"] = num_qubits
        captured_imp["vendor"] = vendor
        return OqCalDocument(
            oq_cal=Header(version="0.1"),
            device=Device(id="stub:dev", num_qubits=num_qubits, vendor=vendor),
            snapshot=Snapshot(source="stub", captured_at="2026-10-31T00:00:00Z"),
        )

    def stub_exporter(doc: OqCalDocument, *, pretty: bool = False, vendor: str = "?") -> dict:
        captured_exp["pretty"] = pretty
        captured_exp["vendor"] = vendor
        return {"id": doc.device.id, "n": doc.device.num_qubits}

    registry.register_importer("optimp", stub_importer)
    registry.register_exporter("optexp", stub_exporter)

    src = tmp_path / "src.json"
    src.write_text("{}")
    r = runner.invoke(
        main,
        [
            "convert", str(src),
            "--from", "optimp", "--to", "optexp",
            "--opt", "num_qubits=7",   # importer-only
            "--opt", "pretty=true",     # exporter-only
            "--opt", "vendor=Acme",     # both
        ],
    )
    assert r.exit_code == 0, r.output
    # int coercion + importer-only param reached the importer
    assert captured_imp["num_qubits"] == 7
    assert captured_imp["vendor"] == "Acme"
    # bool coercion + exporter-only param reached the exporter
    assert captured_exp["pretty"] is True
    assert captured_exp["vendor"] == "Acme"
    # importer did not receive the exporter-only opt (filtered by signature) and
    # vice versa: no TypeError was raised, which proves the filtering worked.
    assert json.loads(r.output) == {"id": "stub:dev", "n": 7}


def test_convert_opt_num_qubits_on_ionq_fixture(runner):
    """Real case: --opt num_qubits=36 on an aggregates-only IonQ fixture."""
    ionq = _FIXTURES_ROOT / "sources" / "braket" / "raw_ionq-forte-1.json"
    r = runner.invoke(
        main,
        [
            "convert", str(ionq),
            "--from", "braket", "--to", "oq-cal",
            "--opt", "num_qubits=36",
        ],
    )
    assert r.exit_code == 0, r.output
    parsed = json.loads(r.output)
    assert parsed["device"]["num_qubits"] == 36


def test_convert_opt_bad_format_errors(runner, tmp_path):
    src = tmp_path / "src.json"
    src.write_text("{}")
    r = runner.invoke(
        main,
        ["convert", str(src), "--from", "oq-cal", "--opt", "noequals"],
    )
    assert r.exit_code != 0


def test_convert_unknown_importer(runner):
    r = runner.invoke(
        main,
        ["convert", str(FIXTURES / "valid_per_qubit.json"), "--from", "nope"],
    )
    assert r.exit_code != 0
    assert "nope" in r.output


def test_convert_list_formats_flag(runner):
    r = runner.invoke(
        main, ["convert", str(FIXTURES / "valid_per_qubit.json"), "--list-formats"]
    )
    assert r.exit_code == 0
    assert "exporters:" in r.output
    assert "braket" in r.output


# ---------------------------------------------------------------------------
# formats
# ---------------------------------------------------------------------------


def test_formats_subcommand(runner):
    r = runner.invoke(main, ["formats"])
    assert r.exit_code == 0
    assert "importers:" in r.output
    assert "exporters:" in r.output
    assert "qiskit" in r.output
    assert "braket" in r.output


# ---------------------------------------------------------------------------
# diff
# ---------------------------------------------------------------------------


def test_diff_human_readable(runner):
    r = runner.invoke(
        main,
        [
            "diff",
            str(FIXTURES / "valid_per_qubit.json"),
            str(FIXTURES / "valid_full_depth.json"),
        ],
    )
    assert r.exit_code == 0, r.output
    assert "drift:" in r.output
    assert "major" in r.output


def test_diff_json(runner):
    r = runner.invoke(
        main,
        [
            "diff",
            str(FIXTURES / "valid_per_qubit.json"),
            str(FIXTURES / "valid_full_depth.json"),
            "--json",
        ],
    )
    assert r.exit_code == 0, r.output
    payload = json.loads(r.output)
    assert "summary" in payload
    assert "entries" in payload
    assert "counts" in payload["summary"]


def test_diff_same_file_all_noise(runner):
    f = str(FIXTURES / "valid_per_qubit.json")
    r = runner.invoke(main, ["diff", f, f, "--json"])
    assert r.exit_code == 0
    payload = json.loads(r.output)
    assert payload["summary"]["counts"]["major"] == 0
    assert payload["summary"]["counts"]["minor"] == 0


# ---------------------------------------------------------------------------
# summary
# ---------------------------------------------------------------------------


def test_summary(runner):
    r = runner.invoke(main, ["summary", str(FIXTURES / "valid_per_qubit.json")])
    assert r.exit_code == 0, r.output
    assert "device:" in r.output
    assert "qubits:" in r.output
    assert "sections:" in r.output
    assert "T1" in r.output


def test_summary_aggregates_only(runner):
    r = runner.invoke(main, ["summary", str(FIXTURES / "valid_aggregates_only.json")])
    assert r.exit_code == 0, r.output
    assert "aggregates" in r.output


# ---------------------------------------------------------------------------
# convert: identity flags + captured_at (feedback 001 + 002)
# ---------------------------------------------------------------------------

_BRAKET_SRC = _FIXTURES_ROOT / "sources" / "braket" / "raw_iqm-garnet.json"
_CEPHEUS_SRC = _FIXTURES_ROOT / "sources" / "braket" / "braket_standardized_cepheus_108.json"


def test_convert_identity_flags(runner, tmp_path):
    out = tmp_path / "o.json"
    r = runner.invoke(
        main,
        [
            "convert", str(_BRAKET_SRC),
            "--from", "braket", "--to", "oq-cal",
            "--device-id", "aws:iqm.garnet",
            "--vendor", "IQM",
            "--model", "Garnet",
            "--captured-at", "2026-10-31T00:00:00Z",
            "--snapshot-id", "demo-0001",
            "-o", str(out),
        ],
    )
    assert r.exit_code == 0, r.output
    doc = json.loads(out.read_text())
    assert doc["device"]["id"] == "aws:iqm.garnet"
    assert doc["device"]["vendor"] == "IQM"
    assert doc["device"]["model"] == "Garnet"
    assert doc["snapshot"]["captured_at"] == "2026-10-31T00:00:00Z"
    assert doc["snapshot"]["id"] == "demo-0001"


def test_convert_flag_wins_over_opt(runner, tmp_path):
    out = tmp_path / "o.json"
    r = runner.invoke(
        main,
        [
            "convert", str(_BRAKET_SRC),
            "--from", "braket", "--to", "oq-cal",
            "--opt", "device_id=from-opt",
            "--device-id", "from-flag",
            "--captured-at", "2026-10-31T00:00:00Z",
            "-o", str(out),
        ],
    )
    assert r.exit_code == 0, r.output
    doc = json.loads(out.read_text())
    assert doc["device"]["id"] == "from-flag"


def test_convert_captured_at_invalid(runner):
    r = runner.invoke(
        main,
        [
            "convert", str(_BRAKET_SRC),
            "--from", "braket", "--to", "oq-cal",
            "--captured-at", "not-a-date",
        ],
    )
    assert r.exit_code != 0
    assert "ISO-8601" in r.output


def test_convert_captured_at_warning_when_absent(runner, tmp_path):
    out = tmp_path / "o.json"
    r = runner.invoke(
        main,
        [
            "convert", str(_BRAKET_SRC),
            "--from", "braket", "--to", "oq-cal",
            "-o", str(out),
        ],
    )
    assert r.exit_code == 0, r.output
    assert "no captured_at" in r.output
    assert "--captured-at" in r.output
    # proceeded: document was still written, without a captured_at.
    doc = json.loads(out.read_text())
    assert "captured_at" not in doc["snapshot"]


# ---------------------------------------------------------------------------
# summary: unmeasured count (feedback 003)
# ---------------------------------------------------------------------------


def test_summary_reports_unmeasured_count(runner, tmp_path):
    registry.load_all()
    oq_cal_out = tmp_path / "cepheus.oq-cal.json"
    r = runner.invoke(
        main,
        [
            "convert", str(_CEPHEUS_SRC),
            "--from", "braket", "--to", "oq-cal",
            "--captured-at", "2026-10-31T00:00:00Z",
            "-o", str(oq_cal_out),
        ],
    )
    assert r.exit_code == 0, r.output
    r2 = runner.invoke(main, ["summary", str(oq_cal_out)])
    assert r2.exit_code == 0, r2.output
    assert "unmeasured: 4 qubits, 29 gate entries" in r2.output


def test_summary_no_unmeasured_line_when_clean(runner, tmp_path):
    oq_cal_out = tmp_path / "garnet.oq-cal.json"
    r = runner.invoke(
        main,
        [
            "convert", str(_BRAKET_SRC),
            "--from", "braket", "--to", "oq-cal",
            "--captured-at", "2026-10-31T00:00:00Z",
            "-o", str(oq_cal_out),
        ],
    )
    assert r.exit_code == 0, r.output
    r2 = runner.invoke(main, ["summary", str(oq_cal_out)])
    assert r2.exit_code == 0, r2.output
    assert "unmeasured:" not in r2.output
