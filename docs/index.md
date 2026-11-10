# Open Quantum Calibration Standard (oq-cal)

oq-cal is a vendor-neutral, JSON-native interchange format for QPU calibration and
characterization data: coherence times, gate and readout fidelities, frequencies,
confusion matrices, and pulse-level parameters. It ships with a reference Python library
and a TypeScript port, with converters to and from the formats in common use today.

**Version 0.1.0.** Each document carries spec version `0.1`.

[Get started](guides/getting-started.md){ .md-button .md-button--primary }
[Read the spec](spec/introduction.md){ .md-button }
[View on GitHub](https://github.com/openquantum-oss/oq-cal-staging){ .md-button }

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

## Design principles

- **SI units are mandatory.** Every datum carries an explicit, SI-canonical unit (`s`,
  `Hz`, `dimensionless`); converters normalize source units (`ns`, `GHz`, `"fraction"`, …)
  to base SI. This removes unit ambiguity, a common source of interoperability bugs.
- **`$n` physical-qubit addressing.** Qubits are referenced by physical index (`$0`, `$1`, …),
  with an optional `qubit_labels` map preserving vendor-native names.
- **Optional sections.** Only `oq-cal`, `device`, and `snapshot` are required. Every data section is optional.
- **Lossless via `extensions`.** Anything that does not map onto a standardized field is
  preserved verbatim under `extensions`, so converting into oq-cal never discards information.
- **OpenQASM conventions.** `stdgates` gate vocabulary, a versioned header as the first
  structural element, and a `defcals` section named after OpenQASM's `defcal`.

## Supported formats

| Format | Import | Export | Notes |
|---|:---:|:---:|---|
| Braket standardized device properties (v1, v3) | ✅ | ✅ | unit normalization (µs→s, `"fraction"`→dimensionless); directional readout errors → confusion matrix; protocol aggregates (e.g. `Two_Qubit_Clifford`) → benchmarks, not gates |
| Boulder Opal (Q-CTRL) snapshot | ✅ | — | components / classifiers / defcals; mixed bare-float and structured values |
| QUAM `state.json` (QUAlibrate) | ✅ | — | duck-typed extraction; full source tree preserved under `extensions` |
| IBM `BackendProperties` JSON | ✅ | — | µs/ns/GHz → base SI; `readout_error` → assignment-error benchmark; full source preserved under `extensions` |
| Rigetti device capabilities (Braket) | ✅ | ✅ | dispatched automatically by the `braket` converter on the Rigetti schema |
| Qiskit `Target` | ✅ | ✅ | export turns any oq-cal doc into a transpiler target |

## Where to go next

<div class="grid cards" markdown>

-   :material-rocket-launch: **[Getting started](guides/getting-started.md)**

    Install from source, run your first conversion, validate and summarize.

-   :material-file-document: **[Specification](spec/introduction.md)**

    The normative v0.1 spec and the JSON Schema.

-   :material-swap-horizontal: **[Converting guides](guides/converting-braket.md)**

    Worked examples for Braket, Boulder Opal, QUAM, and Qiskit.

-   :material-language-python: **[Python API](api/index.md)**

    The reference library: models, validation, diff, importers, exporters.

-   :material-language-typescript: **[TypeScript](typescript.md)**

    The `@openquantum-oss/oq-cal` package.

-   :material-check-decagram: **[Conformance](conformance.md)**

    Cross-language test vectors every implementation must pass.

</div>

## License

Apache-2.0. Copyright 2026 Quantum Rings. See
[`LICENSE`](https://github.com/openquantum-oss/oq-cal-staging/blob/main/LICENSE).
