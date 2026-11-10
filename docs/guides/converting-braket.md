# Converting: AWS Braket

The Braket importer (`braket`) reads `braketSchemaHeader.name` and converts two
AWS Braket documents into oq-cal: standardized gate-model QPU device properties
(versions 1 and 3) and Rigetti device capabilities (version 2). The fixture set
for the standardized schema covers IQM, AQT, and IonQ. The standardized shape has
a matching exporter (`braket`) for the reverse direction. Rigetti capabilities
are import-only.

## Schema versions: v1 and v3

Braket publishes standardized device properties under a `braketSchemaHeader`. The importer
recognizes both schema generations in use today:

| Schema | Typical shape | Example device |
|---|---|---|
| **v1** | `oneQubitProperties` / `twoQubitProperties` maps: per-qubit and per-pair tables | IQM Garnet, IQM Emerald |
| **v3** | adds device-level aggregate fields; may mix them with per-qubit tables or be aggregates-only | AQT Ibex (mixed), IonQ Forte-1 (aggregates-only) |

The importer dispatches on the header automatically; you do not select a version. An
unrecognized schema raises a clear `BraketSchemaError`.

## Normalization rules

The importer's job is to turn vendor-shaped, mixed-unit source data into canonical oq-cal.
The rules it applies:

| Source form | oq-cal result | Rule |
|---|---|---|
| time in µs / ns | `{value, unit: "s"}` | prefixed time → base-SI seconds |
| `"fraction"` unit | `unit: "dimensionless"` | fraction/ratio → dimensionless |
| `{value, unit, standardError}` | datum with `std_error` | `standardError: 0` is dropped (treated as "not reported") |
| directional readout errors | `readout.confusion_matrix` | per-state assignment errors → a square row-stochastic matrix |
| protocol aggregates (e.g. `Two_Qubit_Clifford`) | `benchmarks[*]` | benchmark result, **never** a `gates[*].name` |
| vendor gate aliases | `stdgates` name | e.g. `cphase → cz` where a standard name exists |
| pair fidelities | `gates[*]` on `["$i", "$j"]` | per-pair gate entries |
| `fidelityType` `READOUT`, or a `readoutFidelity` item with no `fidelityType` | `metric: "readout_fidelity"` | the source names a readout fidelity, or the field is the only signal |
| other fidelity types, including a `readoutFidelity` item typed `RANDOMIZED_BENCHMARKING` | `method` set, `metric` omitted | Braket names the protocol, not average versus process fidelity |

!!! warning "Qubit numbering is remapped to 0-based"
    oq-cal `$n` indices are always 0-based (spec §4), but some Braket sources number their
    qubits from 1. The importer detects a 1-based source as one whose qubit evidence
    contains no index `0` but does contain index `1`, and shifts every index down by one.
    IQM Garnet is the canonical case: its source keys `"1"`..`"20"` become `$0`..`$19`, so
    the document has **20** qubits (not the 21 a naive `max + 1` would give, with a phantom
    empty `$0`). When a shift is applied, the original vendor numbering is preserved in
    `device.qubit_labels` (`"$0" → "1"`, `"$1" → "2"`, ...), which is the bridge back to the
    source identities: a consumer showing qubit identities to humans should prefer the label
    over the bare `$n`.

    A source that is **already 0-based is kept verbatim, gaps included**. The Cepheus-108
    payload is the counterexample: it already starts at `"0"`, so no shift happens, no
    `qubit_labels` are synthesized, and because its source omits key `"8"` the document
    stays sparse with `$8` absent. The importer never densifies or renumbers a 0-based
    source.

!!! note "Benchmarks are not gates"
    A protocol aggregate such as `Two_Qubit_Clifford` describes a *benchmarking protocol*,
    not a physical gate, so the importer emits it under `benchmarks` (on the relevant
    qubit, pair, or gate) rather than inventing a gate named `two_qubit_clifford`. This
    matches the spec (§7.4).

## `--opt num_qubits`: aggregates-only sources

Per-qubit payloads (v1) let the importer **infer** `device.num_qubits` as `max index + 1`.
Aggregates-only payloads (e.g. IonQ, whose all-to-all connectivity means no per-qubit table
is published) carry no indices to infer from, so the resulting document legitimately has
**no `num_qubits`**; qubit-reference bound-checking is then skipped.

If you know the count, supply it with `--opt num_qubits=N`. The option is forwarded to the
importer, which uses it as a *floor* for per-qubit payloads and as the authoritative count
for aggregates-only ones.

```bash
# aggregates-only: no qubit count published
oq-cal convert fixtures/sources/braket/raw_ionq-forte-1.json \
  --from braket --to oq-cal -o forte.oq-cal.json
# -> device has no num_qubits; document carries an "aggregates" section

# supply one explicitly
oq-cal convert fixtures/sources/braket/raw_ionq-forte-1.json \
  --from braket --to oq-cal \
  --opt num_qubits=36 -o forte.oq-cal.json
```

!!! tip "`--opt` is filtered by signature"
    `--opt key=value` is offered to *both* the importer and exporter calls and filtered by
    each callable's signature, so `num_qubits` reaches the Braket importer and is ignored
    by an exporter that does not accept it. Values are coerced int → float → bool → str.

## Worked example: IQM Garnet

Convert the real IQM Garnet payload (v1, per-qubit, 1-based source keys `"1"`–`"20"`) and
inspect the result. Because Garnet is 1-based, the importer shifts it to 0-based `$0`–`$19`:

```bash
oq-cal convert fixtures/sources/braket/raw_iqm-garnet.json \
  --from braket --to oq-cal -o garnet.oq-cal.json
```

The lowest qubit, source key `"1"`, becomes `$0`. Note the µs coherence times rendered as
seconds, the `"fraction"` readout fidelity rendered as `dimensionless`, the directional
readout errors collapsed into a `confusion_matrix`, and an RB result landing under
`benchmarks`:

```json
"$0": {
  "t1": { "value": 2.6136884458246837e-05, "unit": "s",
          "std_error": 1.1410913829427858e-06 },
  "t2": { "value": 1.0172940640482857e-05, "unit": "s",
          "std_error": 1.2146445042153614e-06 },
  "readout": {
    "fidelity": { "value": 0.9886, "unit": "dimensionless",
                  "std_error": 0.0010613599645461162, "method": "readout",
                  "metric": "readout_fidelity" },
    "confusion_matrix": [[0.99, 0.01], [0.0128, 0.9872]]
  },
  "benchmarks": [
    { "protocol": "simultaneous_rb",
      "fidelity": { "value": 0.9993574115038416, "unit": "dimensionless",
                    "std_error": 1.6970903887102856e-05, "method": "simultaneous_rb" } }
  ]
}
```

A two-qubit gate entry, shifted from the source pair `"1-2"` to `["$0", "$1"]`, with the
`Two_Qubit_Clifford` protocol aggregate routed to `benchmarks` rather than becoming a gate
name:

```json
{ "name": "cz", "qubits": ["$0", "$1"],
  "fidelity": { "value": 0.996169793691225, "unit": "dimensionless",
                "std_error": 0.00021561831506198772,
                "method": "simultaneous_interleaved_rb" },
  "benchmarks": [
    { "protocol": "two_qubit_clifford",
      "fidelity": { "value": 0.9908029593324924, "unit": "dimensionless",
                    "std_error": 0.00012284434330079618,
                    "method": "simultaneous_interleaved_rb" },
      "qubits": ["$0", "$1"] } ] }
```

The shift is recorded in `device.qubit_labels`, the bridge from the 0-based `$n` back to the
vendor numbering (truncated):

```json
"qubit_labels": {
  "$0": "1", "$1": "2", "$2": "3", "...": "...", "$18": "19", "$19": "20"
}
```

Nothing is discarded: any source field that does not map onto a standardized member is
preserved verbatim under `extensions`.

!!! note "Derived connectivity"
    The importer derives `device.coupling_map` from the `twoQubitProperties` pair keys
    (post-shift, so Garnet's entries are 0-based like the rest of the document).
    Braket v1 pair keys are undirected (IQM CZ is bidirectional), so each pair emits
    **both** directions: the 30 pairs of IQM Garnet become 60 directed entries,
    sorted numerically by `(i, j)`. Payloads without per-pair tables (e.g. IonQ, AQT) carry
    no pair evidence and so produce no `coupling_map`.

!!! warning "Dead elements are marked, not dropped"
    Braket flags an uncalibrated qubit or edge with a sentinel: `fidelity` exactly
    `0.5` together with `standardError` exactly `1`. The importer detects this on
    one-qubit fidelities (RB, simultaneous RB, and READOUT) and two-qubit gate
    fidelities. For a sentinel datum it keeps `value: 0.5`, **drops** the standard
    error (it is a marker, not a measurement), and sets `status: "unmeasured"`.
    The element is preserved in place rather than removed, so indices and
    connectivity stay stable. Per the [spec datum rule](../spec/specification.md#2-the-datum),
    consumers MUST exclude `bad`/`unmeasured` datums from aggregate statistics; the
    bundled Qiskit exporter and `oq-cal summary` already honor this (`summary` reports
    an `unmeasured:` count instead of folding the placeholders into best/worst).

## Rigetti device capabilities

Rigetti on Braket publishes `braket.device_schema.rigetti.rigetti_device_capabilities`
version 2, not the standardized properties schema. That document is a capabilities
record: `paradigm.qubitCount`, a directed `connectivityGraph`, an optional embedded
`standardized` block, and optional pulse ports and frames. It does not invent
T1 or gate errors from the capabilities fields. The same `braket` importer
reads that header:

* copies qubit count and the graph's directed edges into `device`;
* runs the standardized importer on `standardized` when that block is present, and
  only then;
* when `provider.specs` repeats that T1 (`FreeInversionRecovery`) or T2
  (`FreeInductionDecay`) and the standardized block omitted `standardError`,
  copies the specs error onto the datum. A specs value that disagrees with the
  standardized value is left alone, and an error the standardized block already
  carried is not replaced;
* records a pulse frame as a defcal when the frame has a frequency, an associated
  gate, and qubit mappings;
* leaves ports and the native-gate list in `extensions.braket`.

A 1-based graph (no index 0, and index 1 present) is shifted the same way as a
standardized payload. The fictional fixture is
`fixtures/sources/rigetti/synthetic_rigetti_capabilities.json`.

```bash
oq-cal convert fixtures/sources/rigetti/synthetic_rigetti_capabilities.json \
  --from braket --to oq-cal -o rigetti.oq-cal.json
```

## Setting device identity and capture date

Braket standardized payloads carry no device identity and (usually) no timestamp.
Supply them at convert time so each document self-identifies, for example for a
dated device registry:

```bash
oq-cal convert fixtures/sources/braket/raw_iqm-garnet.json \
  --from braket --to oq-cal \
  --device-id aws:iqm.garnet --vendor IQM --model Garnet \
  --captured-at 2026-10-31T00:00:00Z --snapshot-id garnet-2026-10-31 \
  -o garnet.oq-cal.json
```

A supplied flag overrides any source-derived value. `--device-id` falls back to the
constant `braket-device` only when neither a flag nor the source supplies one. See
the [CLI reference](cli.md#oq-cal-convert) for the full flag set and the `captured_at`
warning behavior.

## Exporting back to Braket

The `braket` exporter reads `snapshot.source_schema`. A Rigetti capabilities
document is written back as capabilities version 2: qubit count, the directed
coupling map, defcal frequencies, and a nested standardized block when the
document has per-qubit or per-pair data. Ports and the native-gate list are not
reconstructed; they remain only in `extensions` on the oq-cal document. Every
other document is written as standardized properties version 1.

A fidelity is given a Braket `fidelityType` only when `method` or `metric` names
one. `rb` stays randomized benchmarking, including on a readout field.
`readout_fidelity`, or an untyped `readout.fidelity`, is `READOUT`. An error
becomes `1 - error` only when its metric is `average_gate_error` and its method
names a Braket type.

```bash
oq-cal convert garnet.oq-cal.json --from oq-cal --to braket -o garnet.braket.json
```

See [Qiskit integration](qiskit.md) for the other export target, and
[Conformance](../conformance.md) for how the Braket vectors are pinned.
