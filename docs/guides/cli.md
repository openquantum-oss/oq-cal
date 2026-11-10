# CLI reference

The `oq-cal` command is installed with the `cli` extra (`pip install -e ".[cli,dev]"`). It
wraps the reference library's converters, validator, drift engine, and summarizer.

```text
Usage: oq-cal [OPTIONS] COMMAND [ARGS]...

  oq-cal: vendor-neutral QPU calibration interchange.

Options:
  --version  Show the version and exit.
  --help     Show this message and exit.

Commands:
  convert   Convert FILE between formats via the converter registry.
  diff      Report calibration drift between documents A and B.
  formats   List registered importers and exporters.
  summary   Print a compact overview of an oq-cal document.
  validate  Validate FILE against the oq-cal schema and semantic rules.
```

Every command accepts `--help`.

## `oq-cal convert`

Convert a file between formats via the converter registry.

```text
Usage: oq-cal convert [OPTIONS] FILE

Options:
  --from TEXT         Source format (importer name, or 'oq-cal').
  --to TEXT           Target format (exporter name, or 'oq-cal').
  -o, --output FILE   Output file (default stdout).
  --list-formats      List registered importers/exporters and exit.
  --device-id TEXT    Set device.id on the converted document.
  --vendor TEXT       Set device.vendor.
  --model TEXT        Set device.model.
  --captured-at TEXT  Set snapshot.captured_at (validated as ISO-8601).
  --snapshot-id TEXT  Set snapshot.id.
  --opt KEY=VALUE     Extra option forwarded to the importer and/or exporter
                      (repeatable).
```

- **`--from`** selects an importer, or `oq-cal` to parse an oq-cal document directly.
- **`--to`** selects an exporter, or `oq-cal` to emit canonical oq-cal JSON.
- **`--opt key=value`** (repeatable) is offered to *both* the importer and exporter calls
  and filtered by each callable's signature, so an importer-only parameter (e.g.
  `num_qubits` on the Braket importer) reaches the importer and is ignored by the exporter.
  Values are coerced int → float → `true`/`false` → str.

### Identity and provenance flags

The five first-class flags stamp convert-time device identity and capture
provenance that a source payload may not carry (Braket, for instance, carries
neither a device id nor a timestamp):

| Flag | Sets | Notes |
|---|---|---|
| `--device-id` | `device.id` | Overrides the source-derived id; Braket's `braket-device` is a last-resort fallback only. |
| `--vendor` | `device.vendor` | |
| `--model` | `device.model` | |
| `--captured-at` | `snapshot.captured_at` | Validated as ISO-8601 (accepts a trailing `Z` or an explicit offset, e.g. `2026-10-31T00:00:00Z`). Invalid input is rejected with a clear error naming the expected form. |
| `--snapshot-id` | `snapshot.id` | |

A supplied flag **overrides** any source-derived value, and **wins** over an
`--opt` duplicate of the same key. When, after import, the document still has no
`snapshot.captured_at` (neither the source nor `--captured-at` supplied one), a
one-line warning is printed to stderr and conversion proceeds; the file
modification time is **never** used as a fallback. Pass `--captured-at` to record
the capture date explicitly.

Registered formats:

| Importers | Exporters |
|---|---|
| `boulder-opal` | `braket` |
| `braket` | `qiskit` |
| `ibm-properties` | |
| `qiskit-target` | |
| `quam-state` | |

The two columns are the registered names. A row is not an importer/exporter pair.

```bash
# import Braket -> oq-cal
oq-cal convert fixtures/sources/braket/raw_iqm-garnet.json \
  --from braket --to oq-cal -o garnet.oq-cal.json

# supply a qubit count to an aggregates-only source
oq-cal convert fixtures/sources/braket/raw_ionq-forte-1.json \
  --from braket --to oq-cal --opt num_qubits=36 -o forte.oq-cal.json

# stamp identity + capture date for a dated device registry
oq-cal convert fixtures/sources/braket/raw_iqm-garnet.json \
  --from braket --to oq-cal \
  --device-id aws:iqm.garnet --captured-at 2026-10-31T00:00:00Z -o garnet.oq-cal.json

# oq-cal -> Qiskit Target
oq-cal convert garnet.oq-cal.json --from oq-cal --to qiskit
```

!!! note "Qiskit `Target` import is Python-only"
    The `qiskit-target` importer needs a live `Target` object, not a file, so it is not
    reachable through `convert FILE`. Use [`from_qiskit_target`](qiskit.md#from_qiskit_target-the-reverse-import)
    from Python instead.

## `oq-cal validate`

Validate a file against the schema and semantic rules.

```text
Usage: oq-cal validate [OPTIONS] FILE
```

Exits `0` when valid, `1` otherwise. Prints `OK: document is valid` or one `[error]` line
per issue followed by `INVALID: N error(s)`. See [Validating documents](validating.md).

```bash
oq-cal validate garnet.oq-cal.json
```

## `oq-cal summary`

Print a compact device/calibration overview.

```text
Usage: oq-cal summary [OPTIONS] FILE
```

Reports the populated sections and the worst/best coherence, readout, and gate numbers.
Fields the source does not carry render as `?`. Datums flagged `status: "bad"` or
`"unmeasured"` are excluded from the best/worst extremes (their value is a placeholder,
not a measurement); when any are present, a line such as `unmeasured: 4 qubits, 29 gate
entries` reports the count instead.

```bash
oq-cal summary garnet.oq-cal.json
```

## `oq-cal diff`

Report calibration drift between documents `A` and `B`.

```text
Usage: oq-cal diff [OPTIONS] A B

Options:
  --json  Emit the diff as JSON.
```

Without `--json`, prints a tier count header and one line per changed datum. With `--json`,
emits a structured report with `summary.counts`, `summary.total`, and `worst_offenders`.
See [Diffing calibrations](diffing.md).

```bash
oq-cal diff garnet.oq-cal.json garnet_later.oq-cal.json
oq-cal diff garnet.oq-cal.json garnet_later.oq-cal.json --json
```

## `oq-cal formats`

List registered importers and exporters and exit.

```bash
oq-cal formats
```

```text
importers: boulder-opal, braket, ibm-properties, qiskit-target, quam-state
exporters: braket, qiskit
```
