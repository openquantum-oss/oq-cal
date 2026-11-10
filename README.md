# Open Quantum Calibration Standard (oq-cal)

A vendor-neutral, JSON-native interchange format for QPU calibration and characterization
data: coherence times, gate and readout fidelities, frequencies, confusion matrices, and
pulse-level parameters. Ships with a reference Python library and a TypeScript port, with
converters to and from the formats in common use today.

> **Version 0.1.0.** Each document carries spec version `0.1`. See [CHANGELOG.md](CHANGELOG.md).

## Why

Calibration numbers are published in formats that do not interchange:

- AWS Braket device properties, IBM runtime properties, and IQM calibration sets each use their own schema.
- A Qiskit `Target` and QDMI are in-memory objects with no stable file format.
- QUAM, QUAlibrate, and quantify store control-stack state.
- QUAlibrate and Qibocal describe how a calibration is run. oq-cal stores the measured numbers.

An oq-cal document uses one shape, one set of field names, and SI units for those numbers.

## What an oq-cal document looks like

```json
{
  "oq-cal": { "name": "oq-cal.device_calibration", "version": "0.1" },
  "device": {
    "id": "synthetic:acme.transmon-2",
    "vendor": "Acme",
    "model": "acme-transmon-2",
    "num_qubits": 2,
    "coupling_map": [["$0", "$1"], ["$1", "$0"]]
  },
  "snapshot": {
    "captured_at": "2026-10-30T00:00:00+00:00",
    "source": "acme-cal",
    "source_schema": "acme.snapshot/1"
  },
  "qubits": {
    "$0": {
      "t1": { "value": 1.82e-05, "unit": "s", "std_error": 8.6e-07, "status": "good" },
      "frequency_01": { "value": 4.8213e9, "unit": "Hz" },
      "readout": { "fidelity": { "value": 0.9445, "unit": "dimensionless" } }
    }
  },
  "gates": [
    { "name": "cz", "qubits": ["$0", "$1"],
      "error": { "value": 0.0121, "unit": "dimensionless", "status": "approximate" },
      "duration": { "value": 2.4e-07, "unit": "s" } }
  ]
}
```

Every measured value is a **datum**: `{value, unit}` required, in SI units, with
optional error bars, `median`, `method`, and `status`. Only `oq-cal`, `device`, and
`snapshot` are required; a source emits exactly the sections it can populate.

## Repository layout

oq-cal is a multi-language monorepo. The spec and the shared test data live at the root;
each language implementation lives under its own top-level directory.

```
spec/                  normative v0.1 spec + JSON Schema (language-independent)
python/                reference Python library (pyproject.toml, src/, tests/)
typescript/            TypeScript port (package.json, src/, tests/)
fixtures/
  sources/             raw payloads: braket/, rigetti/, ibm/, boulder-opal/, quam/
  oq-cal-docs/           hand-written valid_*/invalid_* oq-cal documents
  conformance/         cross-language test vectors (manifest.json +
                       expected.oq-cal.json per case); every implementation
                       is checked against the same expected output
```

The reference library is published from `python/`; run everything below from there.

## Quickstart

```bash
cd python
python -m venv .venv && source .venv/bin/activate
pip install -e ".[cli,dev]"
pytest
```

Convert a real Braket device-properties payload into oq-cal, then validate, summarise, and
diff it (paths are relative to the repo root; the fixture set lives in `fixtures/`):

```bash
# import AWS Braket standardized device properties -> oq-cal JSON, stamping the
# device identity and capture date the source does not carry (registry use case)
oq-cal convert ../fixtures/sources/braket/raw_iqm-garnet.json \
  --from braket --to oq-cal \
  --device-id aws:iqm.garnet --captured-at 2026-10-31T00:00:00Z \
  -o garnet.oq-cal.json

# aggregates-only sources (e.g. IonQ) that do not publish a qubit count:
# optionally supply one with --opt (forwarded to the importer)
oq-cal convert ../fixtures/sources/braket/raw_ionq-forte-1.json \
  --from braket --to oq-cal --opt num_qubits=36 -o forte.oq-cal.json

oq-cal validate garnet.oq-cal.json          # schema + semantic checks; exit 0 == valid
oq-cal summary  garnet.oq-cal.json          # compact device/calibration overview
oq-cal diff     garnet.oq-cal.json forte.oq-cal.json     # drift report (here: cross-device comparison)
```

## Python API

```python
from oq_cal import OqCalDocument, validate
from oq_cal.exporters.qiskit import to_qiskit_target

doc = OqCalDocument.model_validate_json(open("garnet.oq-cal.json").read())
assert validate(doc) == []               # [] means valid

target = to_qiskit_target(doc)           # a transpiler-ready qiskit Target
print(target.num_qubits, list(target.operation_names))
```

`to_qiskit_target` turns an oq-cal document into a Qiskit transpiler `Target`. A document
without `device.num_qubits`, such as an aggregates-only trapped-ion payload, cannot build
a `Target`; the exporter raises a `ValueError`.

## TypeScript API

A TypeScript implementation in [`typescript/`](typescript/) reads and writes the same
format and passes the same conformance suite. Not yet published to npm; install from the
monorepo (`cd typescript && npm install && npm run build`). See
[`typescript/README.md`](typescript/README.md) for the full tour.

```ts
import { validate, toCanonicalJson, fromBraket } from "@openquantum-oss/oq-cal";
import type { OqCalDocument } from "@openquantum-oss/oq-cal";

const doc: OqCalDocument = fromBraket(
  JSON.parse(fs.readFileSync("raw_iqm-garnet.json", "utf-8")),
);
if (validate(doc).length === 0) {            // [] means valid
  fs.writeFileSync("garnet.oq-cal.json", toCanonicalJson(doc));
}
```

Also exported: `diff`, `fromBoulderOpal`, `fromQuamState`, and `toBraket`.

## Supported formats

| Format | Import | Export | Notes |
|---|:---:|:---:|---|
| Braket standardized device properties (v1, v3) | ✅ | ✅ | unit normalization (µs→s, `"fraction"`→dimensionless); directional readout errors → confusion matrix; protocol aggregates (e.g. `Two_Qubit_Clifford`) → benchmarks, not gates |
| Boulder Opal (Q-CTRL) snapshot | ✅ | — | components / classifiers / defcals; mixed bare-float and structured values |
| QUAM `state.json` (QUAlibrate) | ✅ | — | duck-typed extraction; full source tree preserved under `extensions` |
| IBM `BackendProperties` JSON | ✅ | — | µs/ns/GHz → base SI; `readout_error` → assignment-error benchmark; full source preserved under `extensions` |
| Rigetti device capabilities (Braket) | ✅ | ✅ | dispatched automatically by the `braket` converter on the Rigetti schema |
| Qiskit `Target` | ✅ | ✅ | export turns any oq-cal doc into a transpiler target |

## Specification

| Document | Contents |
|---|---|
| [`spec/intro.md`](spec/intro.md) | Overview: goals, scope, non-goals, relationship to OpenQASM |
| [`spec/specification.md`](spec/specification.md) | Normative v0.1 specification |
| [`spec/schema/oq-cal-0.1.schema.json`](spec/schema/oq-cal-0.1.schema.json) | JSON Schema (draft 2020-12), the machine-readable authority |

## Design principles

- **SI units are mandatory.** Every datum carries an explicit, SI-canonical unit (`s`, `Hz`,
  `dimensionless`); converters normalize source units (`ns`, `GHz`, `"fraction"`, …) to base
  SI. This removes unit ambiguity, a common source of interoperability bugs.
- **`$n` physical-qubit addressing.** Qubits are referenced by physical index (`$0`, `$1`, …),
  always 0-based (1-based sources are shifted; original numbering survives in `qubit_labels`),
  with an optional `qubit_labels` map preserving vendor-native names.
- **Optional sections.** Only `oq-cal`, `device`, and `snapshot` are required. Every data section is optional.
- **Lossless via `extensions`.** Anything that does not map onto a standardized field is
  preserved verbatim under `extensions`, so converting into oq-cal never discards information.
- **OpenQASM conventions.** `stdgates` gate vocabulary, a versioned header as the first
  structural element, and a `defcals` section named after OpenQASM's `defcal`.

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for dev setup, how to run the tests, and the
spec-change policy.

## License

Apache-2.0. Copyright 2026 Quantum Rings. See [`LICENSE`](LICENSE).
