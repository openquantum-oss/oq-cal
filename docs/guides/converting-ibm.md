# Converting: IBM properties

IBM Quantum publishes calibration as a Qiskit `BackendProperties` dictionary, not as
a Braket standardized-properties document. The `ibm-properties` importer reads that
dictionary from JSON. It does not import Qiskit.

```bash
oq-cal convert fixtures/sources/ibm/synthetic_fictional_transmon2.json \
  --from ibm-properties --to oq-cal -o ibm.oq-cal.json
```

The fictional fixture is not a real backend. The importer expects the shape of
`BackendProperties.to_dict()`:

| Source | oq-cal | Rule |
|---|---|---|
| `qubits[i]` | `$i` | the list index is already 0-based |
| `T1` / `T2` in µs, `readout_length` in ns | datum in seconds | prefixed time → seconds |
| `frequency` / `anharmonicity` in GHz | datum in hertz | |
| `prob_meas1_prep0`, `prob_meas0_prep1` | `readout.confusion_matrix` | row-stochastic: row *i* is the prepared state |
| `readout_error` | benchmark `protocol: "readout"`, `error.metric: "assignment_error"` | not inverted into a fidelity |
| `gate_error` | `gates[*].error` with `metric: "average_gate_error"` | the published error rate, not `1 - fidelity` |
| `gate_length` | `gates[*].duration` in seconds | |
| two-qubit `gates[*].qubits` | `device.coupling_map` | directed, as published |
| `backend_name` | `device.id` | vendor is left unset unless the caller passes one |
| `last_update_date` | `snapshot.captured_at` | a space between date and time is rewritten to `T` |
| the whole dictionary | `extensions.ibm` | verbatim |

A `measure` entry in `gates` is skipped. Readout comes from the per-qubit properties.
