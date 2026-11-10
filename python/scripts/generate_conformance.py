#!/usr/bin/env python3
"""Regenerate the cross-language conformance vectors under ``fixtures/conformance/``.

A *conformance vector* pins the expected output of an oq-cal importer for a given
source payload, so that any implementation (the reference Python library today,
the TypeScript port and others later) can be checked for byte-for-structure
agreement against the same test data.

Layout produced
---------------
``fixtures/conformance/<NN-short-name>/``
    ``manifest.json``        {source, importer, kwargs, description}
    ``expected.oq-cal.json``   the importer's output run through the canonical
                             JSON writer (:func:`oq_cal.io.to_canonical_json`)

``manifest.json.source`` is a path *relative to the ``fixtures/`` root* so the
vectors are self-describing and location-independent. ``importer`` is the name
the converter is registered under in :mod:`oq_cal.registry`.

Determinism
-----------
Generation is deterministic: the importers are pure functions of (payload,
kwargs) and the canonical writer fixes key order, indentation and newline. Run
this script twice and ``git diff`` (or ``--check``) must show no change. The CI
conformance step and ``tests/test_conformance.py`` both rely on this.

Usage
-----
    python scripts/generate_conformance.py           # (re)write all vectors
    python scripts/generate_conformance.py --check    # fail if any vector would change
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from oq_cal import registry
from oq_cal.io import to_canonical_json

# python/scripts/generate_conformance.py -> python/scripts -> python -> repo root
REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPO_ROOT / "fixtures"
CONFORMANCE = FIXTURES / "conformance"


# The conformance vectors. ``source`` is relative to ``fixtures/``; ``importer``
# is a registry name; ``kwargs`` are forwarded to the importer verbatim.
VECTORS: list[dict] = [
    {
        "dir": "01-braket-iqm-garnet",
        "source": "sources/braket/raw_iqm-garnet.json",
        "importer": "braket",
        "kwargs": {},
        "description": "AWS Braket standardized device properties, IQM Garnet (per-qubit, 20 qubits; 1-based source remapped to 0-based).",
    },
    {
        "dir": "02-braket-iqm-emerald",
        "source": "sources/braket/raw_iqm-emerald.json",
        "importer": "braket",
        "kwargs": {},
        "description": "AWS Braket standardized device properties, IQM Emerald (per-qubit, 54 qubits; 1-based source remapped to 0-based).",
    },
    {
        "dir": "03-braket-aqt-ibex-q1",
        "source": "sources/braket/raw_aqt-ibex-q1.json",
        "importer": "braket",
        "kwargs": {},
        "description": "AWS Braket standardized device properties, AQT Ibex (mixed granularity).",
    },
    {
        "dir": "04-braket-cepheus-108",
        "source": "sources/braket/braket_standardized_cepheus_108.json",
        "importer": "braket",
        "kwargs": {},
        "description": "AWS Braket standardized device properties, IQM Cepheus-1 (schema v1, 108 qubits, sparse: one uncharacterized qubit index).",
    },
    {
        "dir": "05-braket-ionq-forte-1",
        "source": "sources/braket/raw_ionq-forte-1.json",
        "importer": "braket",
        "kwargs": {},
        "description": "AWS Braket standardized device properties, IonQ Forte-1 (aggregates-only; no qubit count published).",
    },
    {
        "dir": "06-braket-ionq-forte-1-num-qubits",
        "source": "sources/braket/raw_ionq-forte-1.json",
        "importer": "braket",
        "kwargs": {"num_qubits": 36},
        "description": "IonQ Forte-1 with num_qubits=36 supplied via kwargs — exercises importer kwarg handling in conformance.",
    },
    {
        "dir": "07-braket-ionq-forte-1-enterprise",
        "source": "sources/braket/raw_ionq-forte-1-enterprise.json",
        "importer": "braket",
        "kwargs": {},
        "description": "AWS Braket standardized device properties, IonQ Forte-1 Enterprise (aggregates-only).",
    },
    {
        "dir": "08-boulder-opal-acme-transmon8",
        "source": "sources/boulder-opal/synthetic_acme_transmon8.json",
        "importer": "boulder-opal",
        "kwargs": {},
        "description": "Boulder Opal calibration snapshot (synthetic Acme transmon-8): components, classifiers, defcals, mixed datum shapes.",
    },
    {
        "dir": "09-quam-synthetic-state",
        "source": "sources/quam/synthetic_state.json",
        "importer": "quam-state",
        "kwargs": {},
        "description": "QUAM state.json (synthetic full-depth transmon): per-qubit coherence + pulse defcals.",
    },
    {
        "dir": "10-braket-identity-kwargs",
        "source": "sources/braket/raw_iqm-garnet.json",
        "importer": "braket",
        "kwargs": {
            "device_id": "aws:iqm.garnet",
            "vendor": "IQM",
            "model": "Garnet",
            "captured_at": "2026-10-31T00:00:00+00:00",
            "snapshot_id": "demo-0001",
        },
        "description": "IQM Garnet with convert-time identity/provenance kwargs (device_id/vendor/model/captured_at/snapshot_id) — exercises the importer identity override path.",
    },
    {
        "dir": "11-boulder-opal-lumen-components",
        "source": "sources/boulder-opal/synthetic_lumen_components.json",
        "importer": "boulder-opal",
        "kwargs": {},
        "description": "Fictional Boulder Opal snapshot with no qubit_cal: duration-shaped error bars, a column-stochastic confusion matrix, readout tone on x/sx, and a measured qubit that stays on the roster while disabled.",
    },
    {
        "dir": "12-boulder-opal-lumen-qubit-cal",
        "source": "sources/boulder-opal/synthetic_lumen_qubit_cal.json",
        "importer": "boulder-opal",
        "kwargs": {},
        "description": "Fictional Boulder Opal snapshot where qubit_cal wins over components, null measurements are omitted, and a non-operational qubit stays on the roster.",
    },
    {
        "dir": "13-braket-rigetti-capabilities",
        "source": "sources/rigetti/synthetic_rigetti_capabilities.json",
        "importer": "braket",
        "kwargs": {},
        "description": "Fictional Rigetti device capabilities: connectivity graph, embedded standardized readout, and one pulse-frame frequency. No invented gate errors.",
    },
    {
        "dir": "14-ibm-properties-fictional",
        "source": "sources/ibm/synthetic_fictional_transmon2.json",
        "importer": "ibm-properties",
        "kwargs": {},
        "description": "Fictional Qiskit BackendProperties dictionary: SI unit conversion, directed coupling, assignment error, and average gate error.",
    },
]


def _build_vector(spec: dict) -> tuple[str, str]:
    """Return (manifest_json, expected_oq_cal_json) for one vector spec."""
    source_rel = spec["source"]
    payload = json.loads((FIXTURES / source_rel).read_text(encoding="utf-8"))
    importer = registry.get_importer(spec["importer"])
    doc = importer(payload, **spec["kwargs"])
    expected = to_canonical_json(doc)

    manifest = {
        "source": source_rel,
        "importer": spec["importer"],
        "kwargs": spec["kwargs"],
        "description": spec["description"],
    }
    manifest_json = json.dumps(manifest, indent=2) + "\n"
    return manifest_json, expected


def generate(check: bool) -> int:
    registry.load_all()
    changed: list[str] = []
    for spec in VECTORS:
        vec_dir = CONFORMANCE / spec["dir"]
        manifest_json, expected = _build_vector(spec)
        files = {
            vec_dir / "manifest.json": manifest_json,
            vec_dir / "expected.oq-cal.json": expected,
        }
        for path, content in files.items():
            existing = path.read_text(encoding="utf-8") if path.exists() else None
            if existing != content:
                changed.append(str(path.relative_to(REPO_ROOT)))
                if not check:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(content, encoding="utf-8")

    if check:
        if changed:
            print("conformance vectors are STALE; regenerate them:", file=sys.stderr)
            for c in changed:
                print(f"  {c}", file=sys.stderr)
            return 1
        print(f"conformance OK: {len(VECTORS)} vectors up to date")
        return 0

    if changed:
        print(f"wrote {len(changed)} file(s) across {len(VECTORS)} vectors")
    else:
        print(f"conformance up to date: {len(VECTORS)} vectors unchanged")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--check",
        action="store_true",
        help="do not write; exit non-zero if any vector would change.",
    )
    args = ap.parse_args()
    return generate(check=args.check)


if __name__ == "__main__":
    raise SystemExit(main())
