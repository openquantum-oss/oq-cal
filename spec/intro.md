# Open Quantum Calibration Standard (oq-cal): Introduction

oq-cal is a vendor-neutral, JSON-native interchange format for the calibration and
characterization data of quantum processing units (QPUs), together with a reference
Python library that converts to and from the formats in common use today.

oq-cal describes the *measured behavior of quantum hardware*: the coherence times, gate
and readout fidelities, frequencies, confusion matrices, and pulse-level parameters
that a compiler, scheduler, or scientist needs in order to use a device well. An oq-cal
document is a static, serializable report of what a device's calibration *is at a
point in time*: not a program, not a hardware wiring description, and not a recipe
for how calibration was measured.

## Goals

oq-cal 0.1 aims to provide:

- **A single document shape across vendors.** The same field names, the same datum
  structure, and the same units whether the data originated from AWS Braket device
  properties, a Boulder Opal calibration snapshot, a QUAM state tree, or a Qiskit `Target`.
- **Self-describing, versioned documents.** Every document carries a header naming
  the format and its version, so consumers can dispatch on it without guessing.
- **Partial documents.** Sources differ in what they publish: some report only
  device-level aggregates, some full per-qubit tables, some pulse-level parameters.
  An oq-cal document is valid with only `oq-cal`, `device`, and `snapshot`. A source
  adds the data sections it can populate and omits the rest.
- **Lossless conversion.** Any payload that does not map onto a standardized field is
  preserved verbatim under `extensions`, so round-tripping through oq-cal never
  discards information.
- **Machine-checked structure.** The structure is published as a JSON Schema and
  mirrored by pydantic models, so a valid document has a mechanical definition.

## Scope

oq-cal describes *measured device characteristics*. In 0.1 this covers:

- device identity (id, vendor, model, qubit count, physical-to-vendor label map);
- snapshot provenance (when, from where, under which source schema);
- device-level aggregate metrics;
- per-qubit coherence, frequency, anharmonicity, and readout properties, including
  confusion matrices and readout-classifier parameters;
- per-gate fidelity, error, and duration, with benchmark results;
- per-gate pulse/control parameters.

Values are expressed with explicit, SI-canonical units. Qubits are addressed by
physical index (`$0`, `$1`, …). Gates use the `stdgates` vocabulary
where a standard name exists, with free-form names permitted for native or
benchmark-only operations.

## Non-goals

oq-cal is deliberately *not*:

- **A hardware description language.** Control-stack wiring, instrument settings, LO
  configuration, mixers, and ports are out of scope for the standardized sections;
  where a source carries them, they live untouched in `extensions`. oq-cal reports
  characterization, it does not configure instruments.
- **A calibration orchestration framework.** oq-cal reports results; it does not define
  how calibration is *measured* or *scheduled*. Frameworks such as QUAlibrate and
  Qibocal produce calibration data; oq-cal is a format they (or a converter) can emit.
- **A new surface syntax.** Calibration is data, not a program, and every consumer
  wants to parse it mechanically, so oq-cal is JSON and defines no new grammar.

## Relationship to OpenQASM

OpenQASM deliberately standardizes gate-level pulse *definitions* (`defcal`, `cal`)
but has no concept of T1, T2, or fidelity; it describes *programs*, including how to
realize a gate, but not how well a particular device performs it. oq-cal is
complementary, not competing: it supplies the device characterization that a compiler
would consult when deciding *which* gates and qubits to use, and it reuses OpenQASM's
conventions so the two interoperate cleanly:

- **`$n` physical-qubit addressing**, with an optional `qubit_labels` map preserving
  vendor-native names.
- **The `stdgates` gate vocabulary** (`x`, `sx`, `rz`, `cz`, …), with free-form names
  permitted for native and benchmark gates.
- **A versioned header** as the first structural element.
- **A `defcals` section**, named after OpenQASM's `defcal`, carrying exactly the data
  that would parameterize a `defcal` body.

A natural consumer is therefore a transpiler: any oq-cal document can be turned into a
Qiskit `Target` and used to schedule and route circuits against live calibration.

## Versioning

The **spec version** is independent of the **library version**. The spec version
appears in every document
(`"oq-cal": {"name": "oq-cal.device_calibration", "version": "0.1"}`) as `MAJOR.MINOR`.
Minor versions add optional sections and fields in a backward-compatible way: a
0.1 consumer must tolerate unknown fields (and so the schema and models are
permissive on extra keys outside the required identity header). A major version bump
signals a breaking change to required structure. The JSON Schema is published per
spec version under `spec/schema/`.

oq-cal 0.1 is the current specification. It is checked against public device
payloads from IQM, AQT, and IonQ across two Braket schema versions, and against
synthetic fixtures for the other importers.
