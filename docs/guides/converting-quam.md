# Converting: QUAM / QUAlibrate

The QUAM importer (`quam-state`) converts a QUAM (Quantum Abstraction Machine)
`state.json` tree, as produced by QUAlibrate and the qualibration-libs ecosystem, into
oq-cal. A QUAM state tree is *control-stack state*: it describes how an OPX-style control
stack is wired and configured, with calibration data threaded through it. oq-cal extracts the
characterization and preserves everything else.

## Duck-typed extraction

QUAM state trees vary between versions and lab conventions, so the importer does **not**
assume a fixed schema. Instead it duck-types: it walks the tree looking for qubit-like
nodes (by their keys and shape), pulls coherence, frequency, and pulse parameters wherever
they appear, and is tolerant of missing or renamed fields. This targets the
qualibration-libs vocabulary without being brittle to it.

| QUAM region | oq-cal destination |
|---|---|
| qubit nodes (coherence, frequency, anharmonicity) | `qubits[$n]` |
| qubit channels / operations (pulse params) | `defcals[*]` |
| qubit-pair couplers | `defcals[*]` on the pair |
| native qubit names | `device.qubit_labels` |
| the entire source tree | `extensions.quam` (verbatim) |

Pulse `length` is a sample count. The importer divides it by a sample rate in hertz
found on the pulse, then the channel, then the component, then the tree root
(`sampling_rate`, `sample_rate`, `clock`, `sampling_rate_hz`, or `sample_rate_hz`).
When none of those is present, the rate is the QUA convention of 1 GS/s, so a length
in samples equals a length in nanoseconds. The synthetic fixture has no rate, and its
durations stay on that default.

## Reference resolution

QUAM trees use JSON-pointer-style references (`#/...`) to share configuration: a pulse on
one qubit may point at a waveform defined elsewhere in the tree. The importer **resolves**
these absolute references against the document root so the extracted defcal carries real
values, not a dangling pointer. Resolution is best-effort: an unresolvable reference is
tolerated rather than fatal, so a partially-populated tree still converts.

## Extensions preservation

Because a QUAM tree carries far more than characterization (wiring, instrument settings,
mixer and port configuration), the importer stores the **entire source tree verbatim**
under `extensions.quam`. Conversion into oq-cal is lossless: anything the standardized
sections do not capture is still present, untouched, in `extensions`.

!!! note "Characterization in, control stack preserved"
    oq-cal is a *characterization* interchange, not a hardware description language.
    Control-stack wiring stays in `extensions`; oq-cal reports what the device's calibration
    *is*, not how the instruments are configured.

## Worked example: synthetic QUAM state

Convert the synthetic full-depth transmon state tree (per-qubit coherence + pulse
defcals):

```bash
oq-cal convert fixtures/sources/quam/synthetic_state.json \
  --from quam-state --to oq-cal -o quam.oq-cal.json
```

The device identity, with native qubit names preserved:

```json
"device": {
  "id": "quam-device",
  "num_qubits": 2,
  "qubit_labels": { "$0": "q0", "$1": "q1" }
}
```

The resulting document carries `qubits`, a `defcals` array (per-qubit operations plus the
coupler pair), and the complete source tree under `extensions.quam`:

```json
"extensions": { "quam": { "__class__": "...", "qubits": { "...": "verbatim tree" } } }
```

!!! tip "Supply a device id with `--opt`"
    The QUAM tree carries no canonical device id. If you want a specific one in
    `device.id`, pass `--opt device_id=my-lab:transmon-2`; the option is forwarded to the
    importer.

!!! note "Derived connectivity"
    `device.coupling_map` is derived from the two-qubit evidence actually extracted from
    the tree: the `qubit_pairs` whose couplers carry recognized operations. Each pair
    emits **both** directions, sorted numerically by `(i, j)`; a tree with no recognized
    two-qubit evidence produces no `coupling_map`.

!!! note "Import-only"
    QUAM is supported for **import only**; there is no QUAM exporter. Re-export the
    resulting oq-cal document to Braket or Qiskit as needed.

See [Validating documents](validating.md) and [Diffing calibrations](diffing.md) for what
to do next.
