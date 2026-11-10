# Qiskit integration

`to_qiskit_target` turns an oq-cal document into a Qiskit transpiler `Target`.
`from_qiskit_target` reads a live `Target` back into oq-cal.

!!! note "Qiskit is an optional dependency"
    The Qiskit converters need the optional extra `oq-cal[qiskit]` (`qiskit>=2,<3`).

## `to_qiskit_target`

```python
from oq_cal import OqCalDocument
from oq_cal.exporters.qiskit import to_qiskit_target

doc = OqCalDocument.model_validate_json(open("garnet.oq-cal.json").read())
target = to_qiskit_target(doc)

print(target.num_qubits, list(target.operation_names))
```

Or from the CLI:

```bash
oq-cal convert garnet.oq-cal.json --from oq-cal --to qiskit
```

The mapping is **best-effort and never raises on sparse documents**. A gate error is
the `error` datum when one is present. `1 - fidelity` is used only when `metric` is
`average_gate_fidelity` or `readout_fidelity`, or when `metric` is absent. An absent
metric is an assumption: the exporter warns, then still applies `1 - fidelity`, so a
document written before the field still produces a transpiler error. `process_fidelity`,
`state_fidelity`, `rb_decay`, and any other metric are not converted; the instruction
keeps a duration and gets no error, and the warning names the metric.

Qubit and gate benchmarks become extra instructions named by `protocol` (`rb`,
`interleaved_rb`, …). They are not copied onto `x` or any other physical gate. A
protocol that collides with an instruction already on the target is skipped.

Anything else unmappable (an unknown gate name, a parameterized gate with no known
arity) is reported as a *warning*, not an error.

```python
warnings: list[str] = []
target = to_qiskit_target(doc, on_warning=warnings.append)
# warnings now holds one string per unmappable item; nothing was logged
```

By default warnings are emitted on the `oq_cal.exporters.qiskit` logger. Passing
`on_warning` collects them programmatically and suppresses the log emission.

!!! warning "Missing qubit count is the one hard failure"
    A Qiskit `Target` requires a qubit count. If `device.num_qubits` is absent (which the
    spec permits for aggregates-only payloads, §4), `to_qiskit_target` raises a
    `ValueError` naming the problem rather than guessing. Supply a count upstream (e.g.
    `--opt num_qubits=N` on the Braket import) or use `broadcast_aggregates` with a
    document that carries one.

## `broadcast_aggregates`: making aggregates transpiler-usable

An aggregates-only document has no per-qubit or per-gate granularity, so by default it
produces a `Target` with only a qubit count. Pass `broadcast_aggregates=True` to project
the device-level numbers onto a concrete instruction set:

```python
target = to_qiskit_target(doc, broadcast_aggregates=True)
```

| Aggregate | Broadcast to |
|---|---|
| 1q duration + error | a standard single-qubit instruction set on **every** qubit |
| 2q duration + error | a two-qubit instruction over **every pair in `device.coupling_map`** |

When the document has no `coupling_map`, the 2q aggregate is applied to every ordered
distinct pair, the all-to-all assumption appropriate for trapped-ion devices. This needs a
known qubit count, so pair an aggregates-only Braket import with `--opt num_qubits=N`.

## `from_qiskit_target`: the reverse import

The `qiskit-target` importer reads a live `Target` into an oq-cal document. Because a `Target`
is an in-memory Python object (not a file), this path is driven from Python rather than the
file-oriented CLI:

```python
from oq_cal.importers.qiskit import from_qiskit_target

doc = from_qiskit_target(
    target,
    device_id="aws:iqm.garnet",
    vendor="IQM",
    model="garnet",
)
```

`device_id` is required — a bare `Target` carries no device identity, so you must supply
one. `vendor` and `model` are optional. The result is a normal `OqCalDocument` you can validate, serialize, or
re-export.

## Round-trip

oq-cal → `Target` → oq-cal is a supported round-trip and is exercised in the test suite. Note
it is *lossy by construction*: a `Target` holds only what the transpiler needs (gate
errors, durations, qubit count), so coherence times, confusion matrices, classifiers, and
`extensions` do not survive the trip through Qiskit. Keep the original oq-cal document as the
source of truth.

See [Converting: AWS Braket](converting-braket.md) for producing a document with a qubit
count, and the [Python API](../api/exporters.md) for full signatures.
