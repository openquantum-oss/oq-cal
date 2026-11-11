# Conformance

oq-cal is a multi-language format, so "does this implementation produce correct oq-cal?" needs
a mechanical answer that does not privilege any one language. The **conformance suite** is
that answer: a collection of cross-language test vectors, under `fixtures/conformance/`, that
every implementation is checked against. Pass the vectors and your importer produces the
same canonical output as the reference.

## What a vector is

Each vector is a directory named `NN-name/` holding two files:

| File | Role |
|---|---|
| `manifest.json` | the input: which source payload, which importer, what kwargs, and a description |
| `expected.oq-cal.json` | the output: the canonical oq-cal document the reference importer produces from that input |

The `expected.oq-cal.json` is produced by running the reference importer and passing the
result through the **canonical JSON writer** (`oq_cal.io.to_canonical_json`). The canonical
form is deterministic: regenerating a vector from the same input always produces the same
bytes.

## Manifest format

```json
{
  "source": "sources/braket/raw_iqm-garnet.json",
  "importer": "braket",
  "kwargs": {},
  "description": "AWS Braket standardized device properties, IQM Garnet (per-qubit, 20 qubits; 1-based source remapped to 0-based)."
}
```

| Field | Meaning |
|---|---|
| `source` | path (relative to `fixtures/`) to the raw source payload |
| `importer` | the registered importer name to run |
| `kwargs` | keyword arguments forwarded to the importer (e.g. `{"num_qubits": 36}`) |
| `description` | human-readable summary of what the vector exercises |

## The v0.1 vector set

The suite covers Braket payloads (IQM, AQT, and IonQ), a fictional Rigetti
capabilities document, a fictional IBM properties dictionary, plus the Boulder Opal
and QUAM importers:

| Vector | Importer | Exercises |
|---|---|---|
| `01-braket-iqm-garnet` | `braket` | IQM Garnet, per-qubit, 20 qubits (1-based source remapped to 0-based) |
| `02-braket-iqm-emerald` | `braket` | IQM Emerald, per-qubit, 54 qubits (1-based source remapped to 0-based) |
| `03-braket-aqt-ibex-q1` | `braket` | AQT Ibex, mixed granularity |
| `04-braket-cepheus-108` | `braket` | IQM Cepheus-1, v1, 108 qubits, sparse; dead-element sentinels (4 qubits, 29 CZ edges) flagged `status: "unmeasured"` |
| `05-braket-ionq-forte-1` | `braket` | aggregates-only; no qubit count published |
| `06-braket-ionq-forte-1-num-qubits` | `braket` | `num_qubits=36` kwarg handling |
| `07-braket-ionq-forte-1-enterprise` | `braket` | aggregates-only |
| `08-boulder-opal-acme-transmon8` | `boulder-opal` | components, classifiers, defcals, mixed datum shapes |
| `09-quam-synthetic-state` | `quam-state` | per-qubit coherence + pulse defcals |
| `10-braket-identity-kwargs` | `braket` | convert-time identity/provenance kwargs (`device_id`/`vendor`/`model`/`captured_at`/`snapshot_id`) override the source-derived values |
| `11-boulder-opal-lumen-components` | `boulder-opal` | fictional snapshot with no `qubit_cal`: duration-shaped error bars, confusion-matrix orientation, drive vs readout frequency, full roster |
| `12-boulder-opal-lumen-qubit-cal` | `boulder-opal` | fictional snapshot: `qubit_cal` preferred, null measurements omitted, non-operational qubits kept on the roster |
| `13-braket-rigetti-capabilities` | `braket` | fictional Rigetti capabilities: connectivity, embedded standardized readout, one pulse-frame frequency |
| `14-ibm-properties-fictional` | `ibm-properties` | fictional IBM properties: SI units, directed coupling, assignment error, average gate error |

## How an implementation proves conformance

For each vector:

1. Read `manifest.json`.
2. Load the raw payload at `source`.
3. Run the named `importer` with the given `kwargs`.
4. Serialize the result with your canonical JSON writer.
5. Parse your output and `expected.oq-cal.json`, and assert the two are structurally equal
   (numbers compare numerically).

The reference library does exactly this in `python/tests/test_conformance.py`, and the
TypeScript package in `typescript/tests/conformance.test.ts`. Structural equality is the
bar: byte output may differ across languages in number formatting (`5120` vs `5120.0`),
but every value, field, and ordering-independent structure must match.

## Regeneration policy

The vectors are generated, not hand-written. The reference repository regenerates them with:

```bash
cd python
python scripts/generate_conformance.py        # rewrites fixtures/conformance/
git diff ../fixtures/conformance               # review every changed value
```

!!! warning "A converter change means a vector change"
    Any behavior change to a converter, the models, or the canonical serialization
    **requires regenerating the vectors and reviewing the diff**. The diff is the
    human-readable record of what your change does to real payloads. CI runs
    `generate_conformance.py --check` and fails if the committed vectors are stale, so a
    converter change with unregenerated vectors will not merge. If a diff looks wrong, fix
    the converter rather than committing the vector.

See [CONTRIBUTING.md](https://github.com/openquantum-oss/oq-cal/blob/main/CONTRIBUTING.md)
for the spec-change policy and [TypeScript](typescript.md) for the second implementation.
