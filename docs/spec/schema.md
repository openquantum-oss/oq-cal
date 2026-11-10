# JSON Schema

The oq-cal JSON Schema is the **machine-readable authority** for the format's structure
and types. Where the [normative prose](specification.md) and the schema appear to
disagree, that is a bug to be reported; by design they describe the same thing: the
prose carries the semantics a schema cannot express (unit canonicality, qubit-reference
bounds, confusion-matrix row sums, error-bar exclusivity), and the schema carries
everything structural.

- **Draft:** JSON Schema 2020-12
- **Spec version:** 0.1
- **Raw file:** [`spec/schema/oq-cal-0.1.schema.json`](https://github.com/openquantum-oss/oq-cal-staging/blob/main/spec/schema/oq-cal-0.1.schema.json)

## Copies of the schema

`spec/schema/oq-cal-0.1.schema.json` is the schema. The Python library ships a
byte-identical copy at `python/src/oq_cal/_schema/oq-cal-0.1.schema.json`, and CI
checks the two with `cmp`. Each spec version publishes its own file. A minor version
may only add optional fields. A major version ships a new file.

!!! tip "Validate without the Python library"
    Because the schema is standard JSON Schema 2020-12, any conforming validator can
    schema-check an oq-cal document directly against the raw file. The reference library
    adds the *semantic* layer (units, qubit bounds, matrix sums) on top; see
    [Validating documents](../guides/validating.md).

## Top-level structure

The document root requires `oq-cal`, `device`, and `snapshot`, and permits the
optional data sections. Unknown members outside the `oq-cal` header are tolerated.

| Member | Required | `$defs` definition |
|---|:---:|---|
| `oq-cal` | yes | `header` |
| `device` | yes | `device` |
| `snapshot` | yes | `snapshot` |
| `aggregates` | no | `aggregates` |
| `qubits` | no | map of `qubitRef` → `qubitProperties` |
| `gates` | no | array of `gateEntry` |
| `defcals` | no | array of `defcal` |
| `extensions` | no | open object (verbatim source payloads) |

## Definitions (`$defs`)

The schema factors its building blocks into `$defs`. The outline below mirrors the file;
consult the raw schema for the exact constraints.

| Definition | Type | Required keys | Role |
|---|---|---|---|
| `header` | object | `name`, `version` | The versioned `oq-cal` header. `name` is the const `oq-cal.device_calibration`; `version` is `MAJOR.MINOR`. |
| `device` | object | `id` | Device identity: id, vendor, model, `num_qubits`, `qubit_labels`, `enabled_qubits`, `coupling_map`. |
| `snapshot` | object | `source` | Capture provenance: source, id, `captured_at`, `source_schema`. |
| `datum` | object | `value`, `unit` | A single measured value. Only `value` + `unit` are required; error bars, `median`, `method`, `status`, `updated_at` are optional. |
| `unit` | string | — | SI-canonical unit enum: `s`, `Hz`, `dimensionless`. |
| `status` | string | — | Calibration status enum: `good`, `approximate`, `stale`, `bad`, `unmeasured`. |
| `qubitRef` | string | — | Physical-qubit reference: `^\$[0-9]+$` (e.g. `$0`). |
| `qubitProperties` | object | — | Per-qubit characterization: coherence, frequency, anharmonicity, readout, benchmarks. |
| `readout` | object | — | Per-qubit readout: fidelity, duration, `confusion_matrix`, `classifier`. |
| `confusionMatrix` | array | — | Square matrix; rows index prepared state, columns assigned state; rows sum to ~1. |
| `classifier` | object | — | Readout discriminator parameters. |
| `benchmark` | object | `protocol` | A protocol-level result (e.g. RB) attached to a qubit, pair, or gate. |
| `aggregates` | object | — | Device-level medians and averages. |
| `gateEntry` | object | `name`, `qubits` | A characterized gate on specific qubits. |
| `defcal` | object | `gate`, `qubits` | Per-gate pulse and control parameters. |

For the full set of constraints (patterns, enums, `minimum`/`maximum` bounds, and the
`additionalProperties` policy per definition), read the schema file directly.
