# Changelog

## 0.1.1

- Rigetti import no longer counts pulse-frame component ids toward `device.num_qubits`. Cepheus stays at 108.
- A pulse frame outside that roster is not emitted as a defcal.
- `oq-cal summary` counts a `0.5`/`1` sentinel as an unmeasured benchmark. A qubit is counted only when its coherence and readout are themselves placeholders.

## 0.1.0

First release of the Open Quantum Calibration Standard (oq-cal), spec version 0.1, and the reference libraries.

- Normative specification and JSON Schema for spec version 0.1.
- Python package `oq-cal`: models, validation, canonical JSON, diff, CLI, and
  importers and exporters for Braket, Boulder Opal, QUAM, IBM properties,
  Rigetti capabilities, and Qiskit `Target`.
- TypeScript package `@openquantum-oss/oq-cal`, checked against the same
  conformance vectors.
