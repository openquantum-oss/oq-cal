"""End-to-end integration suite stitching the whole pipeline together.

Three cross-cutting checks the per-module tests do not cover:

* **Braket round-trip matrix** — every ``fixtures/sources/braket/`` payload goes
  importer (via the registry) -> ``validate`` -> ``to_braket_standardized`` ->
  re-import -> ``validate``. The second-generation document is deliberately
  lossy (Braket's standardized schema carries no aggregates/defcals/frequencies)
  but whatever *does* survive must survive faithfully: we assert a shared T1 or
  readout fidelity per fixture where one exists.
* **Import -> validate -> Qiskit Target** for the Boulder Opal and QUAM synthetic
  fixtures, confirming a usable transpiler target comes out where there is
  enough data.
* **CLI end-to-end** via the click runner against real fixture paths: convert
  (IonQ included, now opt-free), validate, summary, and diff.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from oq_cal.cli import main
from oq_cal.exporters.braket import to_braket_standardized
from oq_cal.importers.braket import from_braket_standardized
from oq_cal.importers.boulder_opal import from_boulder_opal
from oq_cal.importers.quam import from_quam_state
from oq_cal.models import OqCalDocument
from oq_cal.registry import get_importer
from oq_cal.validate import validate

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"
BRAKET = FIXTURES / "sources" / "braket"

# Aggregates-only payloads that publish no qubit count; the caller supplies one.
_BRAKET_NQ = {
    "raw_ionq-forte-1.json": 36,
    "raw_ionq-forte-1-enterprise.json": 36,
}

_BRAKET_FILES = sorted(p.name for p in BRAKET.glob("*.json"))


def _first_t1(doc: OqCalDocument):
    for ref in sorted(doc.qubits or {}):
        t1 = doc.qubits[ref].t1
        if t1 is not None:
            return ref, t1.value
    return None, None


def _first_readout_fid(doc: OqCalDocument):
    for ref in sorted(doc.qubits or {}):
        ro = doc.qubits[ref].readout
        if ro is not None and ro.fidelity is not None:
            return ref, ro.fidelity.value
    return None, None


# ---------------------------------------------------------------------------
# Braket round-trip matrix
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", _BRAKET_FILES)
def test_braket_round_trip_matrix(name):
    payload = json.loads((BRAKET / name).read_text())

    # 1. import via the registry importer
    importer = get_importer("braket")
    kwargs = {}
    if name in _BRAKET_NQ:
        kwargs["num_qubits"] = _BRAKET_NQ[name]
    doc = importer(payload, **kwargs)

    # 2. first-generation document validates clean
    assert validate(doc) == [], f"{name} gen-1: {[str(i) for i in validate(doc)]}"

    # 3. export to the Braket standardized shape
    exported = to_braket_standardized(doc)
    assert exported["braketSchemaHeader"]["name"].endswith(
        "standardized_gate_model_qpu_device_properties"
    )

    # 4. re-import the export (num_qubits inferred, or carried over for agg-only)
    reimport = from_braket_standardized(
        exported, num_qubits=doc.device.num_qubits
    )

    # 5. second-generation document validates clean (lossy is fine)
    assert validate(reimport) == [], f"{name} gen-2: {[str(i) for i in validate(reimport)]}"

    # 6. a shared value survives where one exists. Per-qubit fixtures carry T1
    #    and/or readout fidelity through the Braket schema; aggregates-only
    #    fixtures (IonQ) have no per-qubit table and Braket's schema has no
    #    aggregates slot, so nothing per-qubit survives -- for those we assert
    #    the first-generation document carried the aggregate we expect instead.
    ref, t1 = _first_t1(doc)
    if ref is not None:
        assert reimport.qubits is not None
        assert reimport.qubits[ref].t1 is not None
        assert reimport.qubits[ref].t1.value == pytest.approx(t1)
        return

    ref, fid = _first_readout_fid(doc)
    if ref is not None:
        assert reimport.qubits[ref].readout.fidelity.value == pytest.approx(fid)
        return

    # aggregates-only: Braket export is lossy for aggregates; assert gen-1 had them
    assert doc.aggregates is not None
    assert doc.aggregates.gates_1q is not None


# ---------------------------------------------------------------------------
# Boulder Opal / QUAM synthetic -> import -> validate -> Qiskit Target
# ---------------------------------------------------------------------------


def test_boulder_opal_fixture_to_qiskit_target():
    pytest.importorskip("qiskit")
    from oq_cal.exporters.qiskit import to_qiskit_target

    payload = json.loads((FIXTURES / "sources" / "boulder-opal" / "synthetic_acme_transmon8.json").read_text())
    doc = from_boulder_opal(payload, device_id="synthetic:acme.transmon-8")
    assert validate(doc) == []
    target = to_qiskit_target(doc)
    assert target.num_qubits == doc.device.num_qubits
    # the Boulder Opal snapshot carries gates + readout -> a non-empty instruction set
    assert len(target.operation_names) > 0


def test_quam_fixture_to_qiskit_target():
    pytest.importorskip("qiskit")
    from oq_cal.exporters.qiskit import to_qiskit_target

    payload = json.loads((FIXTURES / "sources" / "quam" / "synthetic_state.json").read_text())
    doc = from_quam_state(payload, device_id="synthetic:quam")
    assert validate(doc) == []
    target = to_qiskit_target(doc)
    assert target.num_qubits == doc.device.num_qubits
    # QUAM carries per-qubit T1/frequency -> qubit_properties populated even
    # though it declares no gates.
    assert target.qubit_properties is not None
    assert any(qp.t1 is not None for qp in target.qubit_properties)


# ---------------------------------------------------------------------------
# CLI end-to-end against real fixture paths
# ---------------------------------------------------------------------------


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.mark.parametrize("name", _BRAKET_FILES)
def test_cli_convert_every_braket_fixture(runner, tmp_path, name):
    """Convert each braket fixture to an oq-cal doc on disk and validate it.

    IonQ aggregates-only fixtures now convert without any --opt: num_qubits is
    simply absent from the emitted document.
    """
    out = tmp_path / f"{name}.oq-cal.json"
    r = runner.invoke(
        main,
        [
            "convert", str(BRAKET / name),
            "--from", "braket", "--to", "oq-cal",
            "-o", str(out),
        ],
    )
    assert r.exit_code == 0, r.output
    assert out.exists()
    data = json.loads(out.read_text())
    assert data["oq-cal"]["version"] == "0.1"
    # validate the written document through the CLI too
    rv = runner.invoke(main, ["validate", str(out)])
    assert rv.exit_code == 0, rv.output
    assert "OK" in rv.output


def test_cli_summary_on_converted_doc(runner, tmp_path):
    out = tmp_path / "garnet.oq-cal.json"
    r = runner.invoke(
        main,
        [
            "convert", str(BRAKET / "raw_iqm-garnet.json"),
            "--from", "braket", "--to", "oq-cal", "-o", str(out),
        ],
    )
    assert r.exit_code == 0, r.output
    rs = runner.invoke(main, ["summary", str(out)])
    assert rs.exit_code == 0, rs.output
    assert "device:" in rs.output
    assert "sections:" in rs.output


def test_cli_summary_on_ionq_unknown_qubit_count(runner, tmp_path):
    """IonQ converts opt-free; summary reports the qubit count as unknown."""
    out = tmp_path / "ionq.oq-cal.json"
    r = runner.invoke(
        main,
        [
            "convert", str(BRAKET / "raw_ionq-forte-1.json"),
            "--from", "braket", "--to", "oq-cal", "-o", str(out),
        ],
    )
    assert r.exit_code == 0, r.output
    assert "num_qubits" not in json.loads(out.read_text())["device"]
    rs = runner.invoke(main, ["summary", str(out)])
    assert rs.exit_code == 0, rs.output
    assert "unknown" in rs.output


def test_cli_diff_garnet_vs_emerald_reports_qubit_churn(runner, tmp_path):
    """diff between garnet (21q) and emerald (55q) conversions runs and reports
    added/removed per-qubit entries."""
    garnet = tmp_path / "garnet.oq-cal.json"
    emerald = tmp_path / "emerald.oq-cal.json"
    for src, dst in (
        ("raw_iqm-garnet.json", garnet),
        ("raw_iqm-emerald.json", emerald),
    ):
        r = runner.invoke(
            main,
            [
                "convert", str(BRAKET / src),
                "--from", "braket", "--to", "oq-cal", "-o", str(dst),
            ],
        )
        assert r.exit_code == 0, r.output

    rd = runner.invoke(main, ["diff", str(garnet), str(emerald), "--json"])
    assert rd.exit_code == 0, rd.output
    payload = json.loads(rd.output)
    paths = {e["path"] for e in payload["entries"]}
    # emerald has qubits that garnet does not (55 vs 21) -> appeared entries
    appeared = [
        e for e in payload["entries"]
        if e["a_value"] is None and e["b_value"] is not None and e["path"].startswith("qubits.")
    ]
    assert appeared, "expected qubits present in emerald but not garnet"
    # and the human-readable report runs and summarises drift
    rh = runner.invoke(main, ["diff", str(garnet), str(emerald)])
    assert rh.exit_code == 0, rh.output
    assert "drift:" in rh.output
    assert any(p.startswith("qubits.") for p in paths)
