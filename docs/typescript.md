# TypeScript

A TypeScript package reads and writes the same oq-cal format as the reference Python library,
so Node and browser tooling can produce and consume oq-cal documents without a Python
runtime. It is checked against the cross-language [conformance vectors](conformance.md), so
identical inputs produce structurally identical documents in both languages.

**Version 0.1.0.** The package is not on npm. Build it from `typescript/` in this repository.

## Package

| | |
|---|---|
| Name | `@openquantum-oss/oq-cal` |
| Module system | ESM |
| Node | >= 18 |

```bash
cd typescript
npm install
npm run build
```

## API

The package mirrors the reference library's core operations. Types are shipped with the
package; `OqCalDocument` is the document shape defined by the [spec](spec/specification.md).

### Validation

```ts
import { validate } from "@openquantum-oss/oq-cal";

const issues: ValidationIssue[] = validate(doc);
if (issues.length === 0) {
  // valid
}
```

`validate(doc)` returns an array of `ValidationIssue`: an empty array means valid, exactly
as in Python. It runs the same two layers: schema plus semantic checks (SI units, qubit
bounds, confusion-matrix row sums, error-bar exclusivity). See
[Validating documents](guides/validating.md).

### Canonical serialization

```ts
import { toCanonicalJson } from "@openquantum-oss/oq-cal";

const json: string = toCanonicalJson(doc);
```

`toCanonicalJson(doc)` produces the canonical on-disk form: 2-space indent, empty fields
omitted, stable field order. It matches the Python writer structurally; byte output may
differ between the two languages only in number formatting (`5120` vs `5120.0`).

### Diff

```ts
import { diff } from "@openquantum-oss/oq-cal";

const result = diff(a, b);
```

`diff(a, b)` compares two documents datum-by-datum and returns the drift result, with the
same significance tiers as the Python engine (`major` > 20%, `minor` > 5%, else `noise`).
See [Diffing calibrations](guides/diffing.md).

### Importers

```ts
import {
  fromBraket,
  fromBoulderOpal,
  fromQuamState,
} from "@openquantum-oss/oq-cal";

const doc1 = fromBraket(payload, {
  numQubits: 36,
  deviceId: "aws:iqm.garnet",
  vendor: "IQM",
  model: "Garnet",
  capturedAt: "2026-10-31T00:00:00Z",
  snapshotId: "garnet-2026-10-31",
});
const doc2 = fromBoulderOpal(payload);
const doc3 = fromQuamState(payload, { deviceId: "my-lab:transmon-2" });
```

Every importer accepts the shared convert-time identity / provenance options
`deviceId`, `vendor`, `model`, `capturedAt`, and `snapshotId`. A supplied value
**overrides** whatever the importer would derive from the source; omitting it
leaves the source-derived (or absent) behavior. For Braket, `deviceId` falls back
to `"braket-device"` only when it is not supplied.

| Function | Source | Options |
|---|---|---|
| `fromBraket(payload, { numQubits?, deviceId?, vendor?, model?, capturedAt?, snapshotId? })` | Braket device document. The header selects standardized properties (v1, v3) or Rigetti capabilities (v2) | `numQubits`: floor for per-qubit payloads, authoritative for aggregates-only; plus the shared identity options |
| `fromBoulderOpal(payload, { deviceId?, vendor?, model?, capturedAt?, snapshotId? })` | Boulder Opal (Q-CTRL) snapshot | shared identity options |
| `fromQuamState(payload, { deviceId?, vendor?, model?, capturedAt?, snapshotId? })` | QUAM `state.json` | shared identity options |

These mirror the Python importers one-for-one; see the
[converting guides](guides/converting-braket.md) for the normalization rules each applies.
The Braket importer also applies the dead-element sentinel convention (fidelity
`0.5` + standardError `1` -> `status: "unmeasured"`), identically to Python.

### Exporters

```ts
import { toBraket } from "@openquantum-oss/oq-cal";

const braketPayload = toBraket(doc);
```

`toBraket(doc)` is the registered export. It writes Rigetti capabilities when
`snapshot.source_schema` names that schema, and standardized properties v1
otherwise, matching the Python `braket` exporter.

!!! note "Qiskit is Python-only"
    The Qiskit `Target` converters are Python-specific (they need the `qiskit` package) and
    have no TypeScript equivalent. The TypeScript package covers the format operations and
    the JSON-native importers/exporters.

## Parity with Python

| Operation | Python | TypeScript |
|---|---|---|
| validate | `validate(doc)` | `validate(doc)` |
| canonical JSON | `to_canonical_json(doc)` | `toCanonicalJson(doc)` |
| diff | `diff(a, b)` | `diff(a, b)` |
| import Braket | `from_braket(payload, num_qubits=..., device_id=...)` | `fromBraket(payload, { numQubits, deviceId })` |
| import Boulder Opal | `from_boulder_opal(payload, device_id=...)` | `fromBoulderOpal(payload, { deviceId })` |
| import QUAM | `from_quam_state(payload, device_id=...)` | `fromQuamState(payload, { deviceId })` |
| export Braket | `to_braket(doc)` | `toBraket(doc)` |

Both implementations are checked against the same [conformance suite](conformance.md), so
identical inputs produce the same document.
