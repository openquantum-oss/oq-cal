# Open Quantum Calibration Standard (oq-cal): Specification, version 0.1

**Spec version:** 0.1 · **Schema:** `spec/schema/oq-cal-0.1.schema.json`
(JSON Schema draft 2020-12)

This document is the normative definition of the oq-cal device-calibration interchange
format, version 0.1. The key words MUST, MUST NOT, REQUIRED, SHOULD, SHOULD NOT, MAY,
and OPTIONAL are to be interpreted as in RFC 2119.

The JSON Schema is the machine-readable authority for structure and types; this prose
is the authority for semantics the schema cannot express (unit canonicality, qubit-ref
bounds, confusion-matrix sums, error-bar exclusivity). Where the two appear to
disagree, that is a bug to be reported.

## 1. Document model

An oq-cal document is a single JSON object. The canonical file extension is
`.oq-cal.json`; `.oq-cal` is an accepted alias. Documents SHOULD be UTF-8 encoded.

The top-level object has these members:

| Member | Required | Meaning |
|---|:---:|---|
| `oq-cal` | yes | Versioned schema header |
| `device` | yes | Device identity |
| `snapshot` | yes | Capture provenance |
| `aggregates` | no | Device-level aggregate metrics |
| `qubits` | no | Per-qubit characterization, keyed by `$n` |
| `gates` | no | Per-gate characterization |
| `defcals` | no | Per-gate pulse/control parameters |
| `extensions` | no | Verbatim source payloads, keyed by source name |

A document is **valid** if it carries `oq-cal`, `device`, and `snapshot` and conforms
to the schema. The data sections are all OPTIONAL; a document with only those three
is valid. Consumers MUST probe for data by presence of a section, not by negotiating
a profile. Producers MUST NOT emit a section they cannot populate with at least
identity-correct data.

Unknown members outside the `oq-cal` header MUST be tolerated by consumers and SHOULD be
preserved on round-trip. Producers SHOULD route non-standard source data to
`extensions` rather than inventing top-level members.

### 1.1 The sections, in brief

- **`oq-cal`** is the format header. It names the format and pins the spec version, so a
  consumer can dispatch on it before reading anything else.
- **`device`** says *which machine* this document describes: a stable identifier,
  vendor and model, qubit count, the map from `$n` indices to vendor-native qubit
  labels, which qubits are currently enabled, and the two-qubit connectivity
  (`coupling_map`).
- **`snapshot`** says *when and from where* the data was captured: a timestamp, the
  producing system, the upstream schema the data was converted from, and an optional
  snapshot id (such as a content hash). Together, `device` + `snapshot` make two
  documents comparable: same device, different moments.
- **`aggregates`** holds device-wide summary numbers (median T1 across the device,
  average two-qubit gate fidelity) for sources that publish nothing finer-grained.
- **`qubits`** is the per-qubit characterization table: coherence times, transition
  frequency, anharmonicity, and readout quality for each physical qubit, including
  (when the source provides them) confusion matrices and readout-classifier
  parameters.
- **`gates`** characterizes specific gates on specific qubits: fidelity, error rate,
  duration, and benchmark results for, say, `cz` on `["$3", "$4"]`.
- **`defcals`** carries the pulse-level control parameters behind each calibrated
  gate: drive amplitude, duration, frequency, DRAG coefficient. It is the layer a
  pulse programmer or hardware team works at.
- **`extensions`** preserves whatever the source carried that the standardized
  sections cannot express, verbatim. It is the lossless escape hatch.

### 1.2 Sections are independent

Nothing in the document names a profile or a depth. A consumer tells what a document
contains by which sections are present. Sections do not imply each other: a source
can emit `defcals` without `gates`, and `aggregates` without `qubits`.

| Sections | What it answers | Typical producer | Typical consumer |
|---|---|---|---|
| `oq-cal`, `device`, `snapshot` | Which device, when, from where? | every document (required) | catalogs, provenance tracking, cache keys |
| `aggregates` | How good is this device overall? | vendors that publish device medians only | dashboards, backend selection |
| `qubits`, `gates` | How good is each qubit and each gate? | most cloud providers and lab stacks | transpilers, noise-aware compilation, per-qubit drift monitoring |
| `qubits[*].readout.confusion_matrix`, `classifier` | How does readout misassign states? | lab control stacks; some cloud sources | measurement-error mitigation |
| `defcals` | What drive parameters realize each gate? | control-stack systems | pulse-level programming, OpenQASM `defcal` generation |

Typical shapes:

- A cloud vendor that publishes only device medians produces the required sections plus `aggregates`.
- A cloud vendor with per-qubit tables produces `qubits` and `gates`, sometimes with a confusion matrix.
- A lab control stack often produces those, plus `classifier` and `defcals`, and sometimes `aggregates` as well.

A consumer that only reads the required sections, `qubits`, and `gates` is fully conformant.

## 2. The datum

Every measured value is a **datum**: a JSON object. Only `value` and `unit` are
REQUIRED.

```json
{
  "value": 1.5326e-05,
  "unit": "s",
  "std_error": 7.63e-07,
  "median": 1.531e-05,
  "method": "rb",
  "status": "good",
  "updated_at": "2026-08-10T23:04:42Z"
}
```

| Field | Type | Req. | Notes |
|---|---|:---:|---|
| `value` | number | yes | The measured value, in `unit`. |
| `unit` | string | yes | SI-canonical (see §3). |
| `std_error` | number ≥ 0 | no | Symmetric standard error. |
| `err_minus` | number ≥ 0 | no | Lower asymmetric error bar. |
| `err_plus` | number ≥ 0 | no | Upper asymmetric error bar. |
| `median` | number | no | Median, when `value` is a mean. |
| `method` | string | no | Short id of the measurement protocol, e.g. `rb`, `interleaved_rb`, `readout`. |
| `metric` | string | no | Mathematical quantity the number is. Recommended: `average_gate_fidelity`, `process_fidelity`, `state_fidelity`, `readout_fidelity`, `assignment_error`, `average_gate_error`, `rb_decay`. Any other string is valid. |
| `status` | string | no | One of `good`, `approximate`, `stale`, `bad`, `unmeasured`. |
| `updated_at` | string\|null | no | ISO-8601 timestamp of the measurement. |

`method` and `metric` answer different questions. `method` names the protocol that produced the number. `metric` names what the number *is*. A randomized-benchmarking experiment can report an average gate fidelity, a process fidelity, or the raw decay parameter, and those are not the same quantity.

**Error-bar rules (normative):**

- A datum MUST NOT carry `std_error` together with either `err_minus` or `err_plus`.
  Use one convention or the other.
- `err_minus` and `err_plus` MUST be provided as a pair; a datum MUST NOT carry one
  without the other.
- `std_error: 0` in a *source* payload commonly means "not reported"; converters
  SHOULD drop it rather than emit a spurious zero error.

**Fidelity and error (normative):**

A dimensionless `fidelity` and a dimensionless `error` are not interchangeable. Consumers MUST NOT compute an error as `1 - fidelity` unless `metric` is `average_gate_fidelity` or `readout_fidelity`. `process_fidelity` and `state_fidelity` are different quantities. `rb_decay` is the randomized-benchmarking decay parameter, not an average gate fidelity. `assignment_error` and `average_gate_error` are already error rates; an `average_gate_error` is about `1 - F_avg` and MUST be stored on an `error` datum rather than inverted into a fidelity the source did not publish.

An explicit `error` datum is used as published. It is not derived from `fidelity`. When `metric` is absent, the quantity is whatever the source meant. A consumer that still applies `1 - fidelity` MUST treat that conversion as its own assumption, not as a fact the document stated. Producers that know the quantity MUST set `metric`.

**Dead and uncalibrated datums (normative):**

A datum with `status: "bad"` or `status: "unmeasured"` carries a **placeholder**
`value`, not a measurement. The placeholder exists only so the element keeps its
position in the document; its numeric value MUST NOT be treated as a measured
quantity. Consumers MUST exclude such datums from all aggregate statistics
(means, medians, best/worst extremes, model fitting) and SHOULD omit the affected
element entirely when projecting onto a downstream model that has no notion of an
uncalibrated element (for example, a transpiler target entry). Producers that can
detect a source sentinel for an uncalibrated element (such as a fixed fidelity /
standard-error pair) SHOULD set the `status` marker rather than passing the
placeholder through as an ordinary datum.

## 3. Units

Units are mandatory and MUST be SI-canonical. The permitted unit strings in 0.1 are:

- `"s"`: seconds (time: T1, T2, durations, integration times);
- `"Hz"`: hertz (frequency, anharmonicity);
- `"dimensionless"`: fidelities, errors, probabilities, and other pure numbers.

Non-base and prefixed units (`ns`, `us`, `µs`, `GHz`, `MHz`, `"fraction"`, `"S"`) MUST
NOT appear in standardized sections. Converters are responsible for normalizing source
units to base SI (e.g. `ns → s`, `GHz → Hz`, `"fraction" → "dimensionless"`). This
removes unit ambiguity between producers and consumers.

The sole exception is `extensions`: because it holds verbatim source payloads, any
units there are out of scope and MUST NOT be unit-checked.

Pulse parameters under `defcals[*].params` are an exception to the datum shape (§8):
they use SI-suffixed *keys* (`duration_s`, `frequency_hz`, `integration_time_s`)
carrying bare base-SI numbers, with dimensionless control parameters (`amp`, `motzoi`)
as bare numbers.

## 4. Qubit addressing

Qubits are addressed with OpenQASM physical-qubit notation: a string matching
`^\$[0-9]+$`, a dollar sign followed by the zero-based integer index (`"$0"`,
`"$1"`, …). Every qubit reference anywhere in the document (keys of `qubits`,
`enabled_qubits`, `coupling_map`, `gates[*].qubits`, `defcals[*].qubits`) MUST use
this form, and the integer MUST be less than `device.num_qubits` when that field is
present.

`device.num_qubits` is OPTIONAL. Some sources genuinely do not report a qubit count,
notably aggregates-only trapped-ion payloads (e.g. IonQ Braket device properties)
where all-to-all connectivity means no per-qubit table is published. When
`num_qubits` is absent, `$n` bound-checking is skipped and consumers MUST treat the
qubit count as unknown rather than assuming zero or inferring one. A producer SHOULD
emit `num_qubits` whenever it can determine the count (e.g. a caller supplies it, or
it is inferable from per-qubit/per-pair indices).

Vendor-native labels (e.g. `qA4`, `qD2`) are preserved via `device.qubit_labels`, a
map from `$n` to the native label string. Pairs and multi-qubit operations use ordered
arrays of references, e.g. `["$95", "$96"]`; `device.coupling_map` carries directed
`[$i, $j]` pairs when a source expresses directionality.

An oq-cal `$n` index is ALWAYS 0-based. Producers MUST emit 0-based `$n`. A source that
numbers its qubits from 1 (e.g. some vendors on AWS Braket) MUST be shifted so the
lowest qubit becomes `$0`: a producer treats a source as 1-based when index `0` appears
nowhere in its qubit evidence and index `1` does appear, and then subtracts 1 from every
index. When a producer applies such a shift it SHOULD preserve the original source
identifiers in `device.qubit_labels` (`"$0"` to `"1"`, and so on) so traceability to the
vendor numbering is not lost. A source that is already 0-based is kept verbatim,
INCLUDING gaps: a sparse numbering (e.g. a payload that omits index `8`) is preserved as
is, with `$8` simply absent; producers MUST NOT densify or renumber it.

When a source names qubits with vendor labels rather than integer indices, the
producer assigns `$n` from a stable full roster: the source's declared order when it
has one, otherwise the sorted full set of qubit labels. The roster includes qubits
that are not currently enabled. `device.num_qubits` is the size of that roster.
Producers MUST NOT compact `$n` to the enabled subset, so a qubit keeps its index
when a neighbour is disabled. `device.enabled_qubits` lists the qubits currently
offered, drawn from that roster, and `device.qubit_labels` maps every roster index
to its native label.

**Note:** an oq-cal `$n` does not necessarily equal the qubit number printed in vendor
documentation or in the source payload. The two can differ by the 0-based shift above (a
qubit that a vendor calls `"1"` may be `$0` in oq-cal), and `device.qubit_labels` is the
bridge between them. Consumers that present qubit identities to humans (diagnostics,
dashboards, reports) SHOULD show the `qubit_labels` value when one is present, rather
than the bare `$n`, so that the identity a user sees matches the vendor's.

## 5. Identity

### 5.1 `oq-cal` (header)

```json
{ "name": "oq-cal.device_calibration", "version": "0.1" }
```

- `name` MUST be exactly `"oq-cal.device_calibration"`.
- `version` MUST match `MAJOR.MINOR` (`^[0-9]+\.[0-9]+$`); for this spec, `"0.1"`.
- The header MUST NOT carry additional members.

### 5.2 `device`

| Field | Req. | Notes |
|---|:---:|---|
| `id` | yes | Stable device identifier, e.g. `"aws:iqm.cepheus-1"`. |
| `num_qubits` | no | Integer ≥ 0; the bound for all qubit references. OPTIONAL: some sources (aggregates-only trapped-ion payloads) do not publish a qubit count. See §4. |
| `vendor` | no | Human-readable vendor name. |
| `model` | no | Device model string. |
| `qubit_labels` | no | Map `$n` → vendor-native label. |
| `enabled_qubits` | no | Array of `$n` currently offered for use. There is no separate disabled-qubits member; see the note below. |
| `coupling_map` | no | Array of directed `[$i, $j]` pairs. See derivation semantics below. |

`coupling_map` is **directed**: an entry `["$i", "$j"]` asserts a two-qubit
operation with control/first operand `$i` and target/second operand `$j`.
Producers derive it from two-qubit evidence present in the source
(per-pair gate/benchmark properties, two-qubit defcals or gate errors); they
MUST NOT fabricate connectivity from device-level aggregates or from no evidence.
When the source pair evidence is **undirected** (e.g. a bidirectional CZ keyed by
an unordered qubit pair), producers emit **both** directions `["$i","$j"]` and
`["$j","$i"]`. The array is sorted numerically by `(i, j)`. It is **absent**
entirely when the source carries no two-qubit evidence (e.g. aggregates-only
all-to-all payloads). Consumers that need connectivity but find it absent MUST
treat the topology as unknown (not empty).

`enabled_qubits`, when present, lists the qubits the device currently offers for
use. There is **no** separate disabled-qubits member: a dead or uncalibrated
element is expressed by `status` markers on its datums (see §2) and, when the
source distinguishes usability, by omission of that qubit from `enabled_qubits`.
Producers SHOULD emit `enabled_qubits` when the source provides that distinction,
and SHOULD leave it absent when the source does not (absence means "not stated",
not "all disabled"). A qubit may appear in `enabled_qubits` and still carry
uncalibrated datums; the two mechanisms are independent.

### 5.3 `snapshot`

| Field | Req. | Notes |
|---|:---:|---|
| `source` | yes | Short id of the producing system, e.g. `"aws-braket"`. |
| `id` | no | Snapshot identity (e.g. a content hash). |
| `captured_at` | no | ISO-8601 capture timestamp. |
| `source_schema` | no | Identifier of the source schema the data came from. |

A `source_schema` SHOULD be recorded whenever the data is derived from a known
upstream format, so consumers can trace provenance.

## 6. `aggregates`

Device-level medians/averages, for sources that publish no per-qubit data (e.g.
all-to-all trapped-ion devices) or that mix device-level and per-qubit granularity.
Each leaf is a datum. Aggregates-only sources frequently also omit
`device.num_qubits` (§4), since no per-qubit index exists from which to infer it; such
documents are valid, and consumers treat the qubit count as unknown.

```json
"aggregates": {
  "qubits":   { "t1": {"value": 95.0, "unit": "s"}, "t2": {"value": 1.2, "unit": "s"} },
  "readout":  { "fidelity": {"value": 0.9961, "unit": "dimensionless"},
                "duration": {"value": 1.5e-4, "unit": "s"} },
  "gates_1q": { "fidelity": {"value": 0.99981, "unit": "dimensionless"},
                "duration": {"value": 1.3e-4, "unit": "s"} },
  "gates_2q": { "fidelity": {"value": 0.9939, "unit": "dimensionless"},
                "duration": {"value": 9.7e-4, "unit": "s"} },
  "ops":      { "reset_duration": {"value": 5e-5, "unit": "s"} }
}
```

`gates_1q` / `gates_2q` accept `fidelity`, `error`, and `duration`. `ops` is an open
map of operation name → duration datum (e.g. `reset_duration`).

## 7. `qubits` and `gates`

### 7.1 `qubits`

A map keyed by `$n`. Each value is a per-qubit object:

| Field | Datum? | Notes |
|---|:---:|---|
| `t1`, `t2`, `t2_echo` | yes | Coherence times, `unit: "s"`. |
| `frequency_01` | yes | Qubit transition frequency, `unit: "Hz"`. |
| `anharmonicity` | yes | `unit: "Hz"` (typically negative). |
| `readout` | — | Readout object (§7.2). |
| `benchmarks` | — | Array of benchmark results (§7.4). |

### 7.2 `readout`

| Field | Notes |
|---|---|
| `fidelity` | Datum, `dimensionless`. |
| `duration` | Datum, `s`. |
| `confusion_matrix` | Matrix (§7.3). |
| `classifier` | Classifier object (§7.3). |

### 7.3 Confusion matrix and classifier

`confusion_matrix` is an array of rows. Row *i* holds the probabilities of assigning
each outcome given prepared state *i*; for a two-outcome readout it is
`[[P(0|0), P(1|0)], [P(0|1), P(1|1)]]`. Each row MUST sum to approximately 1 (within a
tolerance of 0.02 in this spec). The matrix MUST be square. A producer that receives
a column-stochastic matrix (the columns sum to approximately 1 and the rows fit that
rule less well) MUST transpose it before storing it. The original matrix stays in
`extensions` with the rest of the source payload.

`classifier` carries readout-discriminator parameters: `type` (e.g. `"linear_iq"`),
`projection` (array of numbers), `threshold` (number), `status` (string). Additional
fields are permitted.

### 7.4 `gates`

An array; each entry characterizes a gate on specific qubits:

| Field | Req. | Notes |
|---|:---:|---|
| `name` | yes | `stdgates` name where one exists (`x`, `sx`, `rz`, `cz`, `cx`, `swap`, …); otherwise a native or benchmark name (see §9). |
| `qubits` | yes | Ordered array of `$n`, length ≥ 1. |
| `fidelity` | no | Datum, `dimensionless`. |
| `error` | no | Datum, `dimensionless`. |
| `duration` | no | Datum, `s`. |
| `benchmarks` | no | Array of benchmark results. |

A **benchmark** is a protocol-level result that is not itself a physical gate:
`{ "protocol": "rb" | "simultaneous_rb" | "interleaved_rb" | ..., "fidelity": <datum>,
"error": <datum>, "qubits": [...] }`. Protocol aggregates such as
`Two_Qubit_Clifford` MUST be represented as benchmarks (on a qubit, pair, or gate),
never as `gates[*].name`. `fidelity` and `error` on a gate or benchmark follow the
rule in §2: one is not derived from the other unless `metric` allows it.

## 8. `defcals`

An array mirroring OpenQASM's `defcal`: the pulse/control parameters that would
parameterize a `defcal` body. Each entry:

| Field | Req. | Notes |
|---|:---:|---|
| `gate` | yes | Gate name (`stdgates` or native, plus `measure`). |
| `qubits` | yes | Ordered array of `$n`, length ≥ 1. |
| `params` | no | Open map of pulse parameters. |

`params` deliberately does *not* use the datum shape. Keys that carry a physical
quantity encode the SI unit as a suffix and hold a bare base-SI number: `duration_s`,
`frequency_hz`, `integration_time_s`. Dimensionless control parameters are bare
numbers: `amp` (0–1 drive amplitude), `motzoi` (DRAG coefficient). Producers MAY add
further parameters; consumers MUST tolerate unknown keys.

On a drive gate (`x`, `sx`, and the other single-qubit drives), `frequency_hz` is
the qubit drive frequency, not the readout tone. The readout frequency belongs on
the `measure` defcal. Control-stack wiring that is not a pulse parameter stays in
`extensions`.

```json
{ "gate": "measure", "qubits": ["$0"],
  "params": { "duration_s": 2.0e-06, "amp": 0.0355,
              "frequency_hz": 6.7102e9, "integration_time_s": 1.8e-06 } }
```

## 9. Gate naming

Gate names in `gates` and `defcals` SHOULD use the `stdgates.inc` vocabulary where a
standard name exists: `x`, `y`, `z`, `h`, `s`, `sx`, `rx`, `ry`, `rz`, `cx`, `cz`,
`swap`, `ccx`, plus `measure` and `reset` for the corresponding operations. Converters
SHOULD map vendor aliases onto standard names (e.g. `x90 → sx`, `cphase → cz`,
`cnot → cx`).

Names that have no `stdgates` equivalent (native gates such as `gpi2`, `ms`, `zz`,
and benchmark protocols) are permitted as free-form strings. Benchmark protocols MUST NOT
appear as gate names (§7.4). This mirrors Braket's `gateName: str`, which allows any
string while the ecosystem converges on standard names.

## 10. Extensions

`extensions` is a map from source name to a verbatim source payload (any JSON). It
exists so that conversion into oq-cal is never lossy: anything a source carries that does
not map onto a standardized field is preserved here untouched. Content under
`extensions` is out of scope for all semantic rules in this spec; in particular, it is
NOT unit-checked and its qubit identifiers need not follow `$n`. For this version,
ports, feedlines, resonator linewidth, traveling-wave parametric amplifier settings,
and controller wiring stay in `extensions` rather than in standardized fields.

```json
"extensions": { "braket": { "...": "verbatim provider payload" } }
```

## 11. Validation

A conforming validator performs two layers:

1. **Schema validation** against `spec/schema/oq-cal-0.1.schema.json` (draft 2020-12).
2. **Semantic validation** of the rules the schema cannot express:
   - units are SI-canonical (§3);
   - every `$n` reference is well-formed and, when `device.num_qubits` is present,
     `< device.num_qubits` (§4);
   - confusion-matrix rows sum to ~1 (§7.3);
   - `std_error` does not co-occur with `err_minus`/`err_plus`, and the asymmetric
     pair is complete (§2);
   - the `extensions` subtree is exempt from semantic checks (§10).

The reference implementation exposes this as `oq_cal.validate(doc) -> list[issue]`; an
empty list denotes a valid document.

## 12. Versioning and conformance

The spec version (`oq-cal.version`) is independent of any implementation's version. A
MINOR increment MAY add OPTIONAL sections/fields and MUST remain backward compatible;
consumers MUST tolerate unknown fields outside the `oq-cal` header. A MAJOR increment MAY
change required structure. Each spec version publishes its own JSON Schema under
`spec/schema/`.

A **conforming producer** emits documents valid under §11 for the spec version it
declares. A **conforming consumer** accepts any document valid under the declared spec
version, ignores unknown members gracefully, and does not require OPTIONAL sections to
be present.
