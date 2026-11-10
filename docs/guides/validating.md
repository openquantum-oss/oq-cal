# Validating documents

oq-cal validation is **two-layer**: a document is valid only if it passes both. The reference
implementation exposes this as `oq_cal.validate(doc) -> list[ValidationIssue]` (an empty
list means valid), and the CLI wraps it as `oq-cal validate`.

## The two layers

| Layer | What it checks | Authority |
|---|---|---|
| **1. Schema** | structure and types | `spec/schema/oq-cal-0.1.schema.json` (JSON Schema 2020-12) |
| **2. Semantic** | rules the schema cannot express | the [normative prose](../spec/specification.md), §11 |

The semantic layer covers:

- **Units are SI-canonical**: `s`, `Hz`, `dimensionless` only (§3).
- **Qubit references are well-formed**: every `$n` matches `^\$[0-9]+$` and, when
  `device.num_qubits` is present, `< num_qubits` (§4). When `num_qubits` is absent, the
  bound check is skipped.
- **Confusion-matrix rows sum to ~1**: within a tolerance of 0.02 (§7.3). (The spec
  also requires the matrix to be square; the reference validator does not yet enforce
  that.)
- **Error-bar exclusivity**: `std_error` must not co-occur with `err_minus`/`err_plus`,
  and the asymmetric pair must be complete (§2).
- **`extensions` is exempt**: its subtree is never unit-checked or `$n`-checked (§10).

## Anatomy of an issue

Each finding is a `ValidationIssue` with three fields:

| Field | Meaning |
|---|---|
| `severity` | `"error"` (currently the only severity emitted) |
| `path` | slash-delimited location of the offending node, e.g. `qubits/$0/t1/unit` |
| `message` | human-readable description |

```python
from oq_cal import validate
import json

doc = json.load(open("suspect.oq-cal.json"))
for issue in validate(doc):
    print(f"[{issue.severity}] {issue.path}: {issue.message}")
```

## From the CLI

```bash
oq-cal validate garnet.oq-cal.json
```

A valid document:

```text
OK: document is valid
```

The command exits `0` when valid and `1` otherwise, so it drops straight into CI or a
pre-commit hook.

## Worked example: a non-SI unit

The fixture set ships deliberately-invalid documents. `invalid_non_si_unit.json` stores
T1 in nanoseconds and a frequency in gigahertz, both forbidden by §3:

```bash
oq-cal validate fixtures/oq-cal-docs/invalid_non_si_unit.json
```

```text
[error] qubits/$0/frequency_01/unit: 'GHz' is not one of ['s', 'Hz', 'dimensionless']
[error] qubits/$0/t1/unit: 'ns' is not one of ['s', 'Hz', 'dimensionless']
[error] qubits/$0/t1/unit: non-SI unit 'ns' (allowed: ['Hz', 'dimensionless', 's'])
[error] qubits/$0/frequency_01/unit: non-SI unit 'GHz' (allowed: ['Hz', 'dimensionless', 's'])
INVALID: 4 error(s)
```

Note that each bad unit is caught **twice**: once by the schema layer (the `unit` enum)
and once by the semantic layer (the non-SI-unit check). That redundancy is intentional: it
confirms both layers agree, and either layer alone would reject the document.

## Common failures

| Symptom | Cause | Fix |
|---|---|---|
| `non-SI unit 'ns'` / `'GHz'` / `'fraction'` | a prefixed or non-canonical unit leaked into a standardized section | normalize to base SI in the producer; `extensions` is exempt |
| `qubit reference $4 out of range (num_qubits=4)` | a qubit reference out of bounds | fix the index, or drop `num_qubits` if the count is genuinely unknown |
| confusion-matrix row does not sum to ~1 | rows transposed, or missing a column | ensure row *i* is `P(assigned | prepared=i)` and rows are stochastic |
| `std_error` with `err_minus`/`err_plus` | both error conventions on one datum | keep one convention per datum |
| missing `oq-cal` / `device` / `snapshot` | a required section absent | add the identity header; see [the spec](../spec/specification.md) §5 |

See [Diffing calibrations](diffing.md) to compare two valid documents over time.
