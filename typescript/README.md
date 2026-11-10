# Open Quantum Calibration Standard (oq-cal) (TypeScript)

TypeScript reference implementation of **oq-cal**, the vendor-neutral JSON interchange
format for QPU calibration and characterization data. It reads and writes the same
documents as the Python reference library and passes the same cross-language
conformance suite.

> **Version 0.1.0.** Spec version `0.1`. Not published to npm; build it from this directory.

## Install

From a checkout of the repository:

```bash
cd typescript
npm install
npm run build   # emits dist/
```

Then depend on it locally (e.g. `npm install /path/to/oq-cal-staging/typescript`) or import from a
workspace.

## API

```ts
import {
  validate,
  toCanonicalJson,
  diff,
  fromBraket,
  fromBoulderOpal,
  fromQuamState,
  toBraket,
} from "@openquantum-oss/oq-cal";
import type { OqCalDocument, ValidationIssue } from "@openquantum-oss/oq-cal";

// 1. Import a vendor payload -> an oq-cal document
const payload = JSON.parse(fs.readFileSync("raw_iqm-garnet.json", "utf-8"));
const doc = fromBraket(payload);                    // header selects the Braket schema
// aggregates-only sources (e.g. IonQ) may not publish a qubit count:
const forte = fromBraket(ionqPayload, { numQubits: 36 });

// 2. Validate (schema + semantic checks); [] means valid
const issues: ValidationIssue[] = validate(doc);
if (issues.length) console.error(issues);

// 3. Serialize to the canonical on-disk form (2-space indent, trailing newline)
fs.writeFileSync("garnet.oq-cal.json", toCanonicalJson(doc));

// 4. Compare two snapshots for calibration drift
const report = diff(docA, docB);
console.log(report.summary());

// 5. Export back to a Braket standardized-properties object (v1)
const braket = toBraket(doc);
```

Other importers:

```ts
const boulderOpal = fromBoulderOpal(snapshotPayload); // Boulder Opal (Q-CTRL) snapshot
const quam = fromQuamState(stateJson, { deviceId: "acme-8" }); // QUAM state.json
```

### `ValidationIssue`

```ts
interface ValidationIssue {
  severity: "error" | "warning";
  path: string;    // dotted/slashed location of the finding
  code: string;    // stable machine code (e.g. "non_si_unit", "qubit_ref_out_of_range")
  message: string; // human-readable message (mirrors the Python library)
}
```

## Types and schema sync

`src/generated/schema.ts` (TypeScript types) and `src/generated/schema.json` (the runtime
schema used by `validate`) are both generated from the canonical
`spec/schema/oq-cal-0.1.schema.json`:

```bash
npm run generate
```

The spec schema is the single source of truth. After any schema change, run
`npm run generate` and commit the regenerated outputs. CI runs the generator and
`git diff --exit-code` to guarantee the committed outputs stay in sync.

## Conformance

This package passes the shared cross-language conformance suite in
`fixtures/conformance/`. For each vector the importer output, run through `toCanonicalJson` and
re-parsed, is **structurally equal** to the pinned `expected.oq-cal.json`. Byte-for-byte
equality with the Python canonical writer is best-effort (JS and Python format some floats
differently in text, but those parse to identical numbers); structural equality is the
conformance bar.

## Tests

```bash
npm test       # vitest: conformance + validator + diff + canonical + exporter
```

## License

Apache-2.0.
