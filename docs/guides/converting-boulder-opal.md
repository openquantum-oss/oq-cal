# Converting: Boulder Opal

The Boulder Opal importer (`boulder-opal`) converts a *Boulder Opal calibration
snapshot* (Q-CTRL's Boulder Opal product) into oq-cal. These snapshots come from control-stack
tooling that sits at the hardware edge and emits a device-wide calibration state: a mix of
per-qubit characterization, readout classifiers, and pulse-level defcals, often with values
stored in inconsistent shapes.

## Source shapes

A Boulder Opal snapshot mixes several shapes. The importer normalizes them:

- **Mixed value shapes.** The same quantity may appear as a bare float, as a structured
  `{value, err_minus, err_plus, calibration_status, updated_at}` object, or as a duration
  `{value: {value, unit: "ns", dtype: "duration"}}` whose error bars are duration objects
  too. Newer snapshots also carry `qubit_cal`, whose values are already in seconds and
  hertz. The importer normalizes all of these into the oq-cal datum shape. A null
  `qubit_cal` field is omitted. An `unmeasured` component whose value is 0 is omitted.
- **Mixed units.** Times may be in µs or ns; the importer converts everything to base-SI
  seconds. Error bars that are bare numbers are scaled with the value. Error bars that
  carry their own unit are converted from that unit.
- **Vendor-native qubit labels.** Qubits are named (`qA0`, `qA1`, …). `$n` comes from the
  full roster: `qubit_cal` order when that list is present, otherwise the sorted union of
  transmon labels and `enabled_qubits`. Disabling a qubit does not renumber the others.
  `device.num_qubits` is the roster size. `device.enabled_qubits` lists only the qubits
  the device currently offers. `device.qubit_labels` keeps every native name.
- **Column-stochastic confusion matrices.** Boulder stores columns that sum to 1. oq-cal
  stores rows that sum to 1, so the importer transposes a matrix when the columns fit
  that rule more tightly than the rows. The original payload stays in `extensions`.
- **Readout tone on drive defcals.** On this stack, `x` and `sx` `frequency` is the
  readout LO when it matches the `measure` defcal. The importer writes the qubit drive
  (`qubit_cal.frequency`, otherwise `freq_01`) into `frequency_hz` in that case. The
  `measure` defcal keeps the readout frequency. The OpenQASM `program` string is copied
  through and is not parsed.
- **Identity.** `device.id` and `device.model` come from `qpu_model`. `vendor` is left
  unset unless the caller passes it: the snapshot names the chip, not the control
  software. `snapshot.captured_at` is the `version` string rewritten to RFC 3339.
  Caller overrides still win.

`qubit_cal`, when present, wins for T1, T2, T2 echo, frequency, and anharmonicity.
Components remain the source for pulses, bias, and classifiers, and the fallback when
`qubit_cal` is absent. Ports, feedlines, resonator linewidth, TWPA settings, and the
controller wiring stay in `extensions` for 0.1.

## Section mapping

| Source region | oq-cal destination |
|---|---|
| `qpu_model` | `device.id` and `device.model` |
| `version` | `snapshot.captured_at` (RFC 3339) |
| roster (`qubit_cal` order, else sorted transmon labels ∪ `enabled_qubits`) | `device.num_qubits`, `device.qubit_labels` |
| operational / `enabled_qubits` | `device.enabled_qubits` |
| `qubit_cal`, else `components` (coherence, frequency) | `qubits[$n]` |
| `classifiers` | `qubits[$n].readout` (row-stochastic confusion matrix, fidelity, classifier) |
| `gate_errors` | `gates[*]` (omitted when the source has none) |
| `defcals` | `defcals[*]` |
| anything unmapped, including the original payload | `extensions.boulder_opal` |

Classifiers land under `qubits[$n].readout`. The fidelity is the mean of the confusion-matrix
diagonal (`method: "confusion_matrix_diagonal"`). Defcals map onto the `defcals`
array with pulse parameters keyed by SI-suffixed names (`duration_s`, `frequency_hz`,
`integration_time_s`) alongside bare dimensionless controls (`amp`, `motzoi`).

## Worked example: Acme transmon-8

Convert the synthetic Acme transmon-8 snapshot (components, classifiers, defcals, mixed
datum shapes). This file has no `qubit_cal`, so the roster is the sorted enabled labels
`qA0`–`qA5`:

```bash
oq-cal convert fixtures/sources/boulder-opal/synthetic_acme_transmon8.json \
  --from boulder-opal --to oq-cal -o acme.oq-cal.json
```

The device identity comes from `qpu_model`, and the capture time is RFC 3339:

```json
"device": {
  "id": "acme-transmon-8",
  "model": "acme-transmon-8",
  "num_qubits": 6,
  "qubit_labels": { "$0": "qA0", "$1": "qA1", "$2": "qA2",
                    "$3": "qA3", "$4": "qA4", "$5": "qA5" },
  "enabled_qubits": ["$0", "$1", "$2", "$3", "$4", "$5"]
}
```

```json
"snapshot": {
  "captured_at": "2026-09-02T11:20:05.512300+00:00",
  "source": "boulder-opal",
  "source_schema": "boulder-opal-snapshot"
}
```

A per-qubit entry carries the readout classifier alongside the fidelity and confusion
matrix. The Acme matrix is already row-stochastic, so it is stored unchanged:

```json
"$0": {
  "readout": {
    "fidelity": { "value": 0.9445, "unit": "dimensionless",
                  "method": "confusion_matrix_diagonal" },
    "confusion_matrix": [[0.961, 0.039], [0.072, 0.928]],
    "classifier": { "type": "linear_iq", "projection": [-48.113, -5.902],
                    "threshold": 0.2041, "status": "calibrated" }
  }
}
```

The Acme `x` frequency is already the drive, so `frequency_hz` stays `4821335012`.

Two more fictional snapshots sit next to it. `synthetic_lumen_components.json` has no
`qubit_cal`: error bars are duration objects, the confusion matrix is column-stochastic
(and gets transposed), `x` stores the readout tone, and a measured qubit that is not
enabled keeps its index. `synthetic_lumen_qubit_cal.json` is the same made-up device
with `qubit_cal` filled in, including null measurements. Neither file is a real device.

!!! note "Derived connectivity"
    `device.coupling_map` is derived from the two-qubit evidence in the snapshot: 2q
    defcal keys (e.g. `cz:qA0_qA1`) and two-qubit `gate_errors` entries, mapped through
    the label → `$n` table. Each pair emits **both** directions, sorted numerically by
    `(i, j)`; only pairs whose labels are both on the roster contribute. A snapshot
    with neither is left without a coupling map. The importer does not invent one.

!!! note "Export is import-only"
    The Boulder Opal format is supported for **import only**; there is no Boulder Opal
    exporter. Once in oq-cal, a document can be re-exported to Braket or Qiskit like any
    other.

Validate the result as usual:

```bash
oq-cal validate acme.oq-cal.json
```

See [Validating documents](validating.md) for the two-layer validator and
[Diffing calibrations](diffing.md) to compare two Boulder Opal snapshots over time.
