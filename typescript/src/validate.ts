// Validation for oq-cal documents: JSON-Schema (Ajv draft 2020-12) plus the
// semantic layer. Mirrors python/src/oq_cal/validate.py exactly.
//
// validate(doc) returns a list of ValidationIssue; an empty list means valid.
//
// ValidationIssue shape: { severity, path, code, message }. python's issue
// carries { severity, path, message }; we additionally attach a stable `code`
// (per the TS public surface) so callers can branch on the finding type without
// parsing the human message. The `severity`, `path`, and `message` fields
// mirror python's fields and messages verbatim.

import { Ajv2020 } from "ajv/dist/2020.js";
import type { ValidateFunction } from "ajv/dist/2020.js";
type Ajv = Ajv2020;
import * as addFormatsModule from "ajv-formats";
import schema from "./generated/schema.json" with { type: "json" };

// ajv-formats ships as CJS; under NodeNext the callable is the module default
// (sometimes nested one level deeper under interop).
type AddFormats = (ajv: Ajv) => Ajv;
const addFormatsCandidate = (addFormatsModule as unknown as { default?: unknown }).default ??
  addFormatsModule;
const addFormats = ((addFormatsCandidate as { default?: unknown }).default ??
  addFormatsCandidate) as AddFormats;

export type Severity = "error" | "warning";

export interface ValidationIssue {
  severity: Severity;
  path: string;
  code: string;
  message: string;
}

const QUBIT_RE = /^\$([0-9]+)$/;
const SI_UNITS = new Set(["s", "Hz", "dimensionless"]);
const CM_ROW_TOLERANCE = 0.02;
const SI_UNITS_SORTED = ["Hz", "dimensionless", "s"]; // sorted(), for message parity

let _validator: ValidateFunction | undefined;

function schemaValidator(): ValidateFunction {
  if (_validator === undefined) {
    const ajv = new Ajv2020({ allErrors: true, strict: false });
    addFormats(ajv);
    _validator = ajv.compile(schema as object);
  }
  return _validator;
}

export function validate(doc: unknown): ValidationIssue[] {
  const data = asRecord(doc);
  const issues: ValidationIssue[] = [];
  issues.push(...schemaIssues(data));
  issues.push(...semanticIssues(data));
  return issues;
}

function asRecord(doc: unknown): Record<string, unknown> {
  if (typeof doc === "string") return JSON.parse(doc) as Record<string, unknown>;
  if (isObject(doc)) return doc;
  throw new TypeError(`cannot validate object of type ${typeof doc}`);
}

// ---------------------------------------------------------------------------
// Schema layer
// ---------------------------------------------------------------------------

function schemaIssues(data: Record<string, unknown>): ValidationIssue[] {
  const validator = schemaValidator();
  const ok = validator(data);
  if (ok) return [];
  const errors = validator.errors ?? [];
  const issues = errors.map((err) => {
    // instancePath is a JSON Pointer like "/qubits/$0/t1"; python uses the
    // absolute path joined by "/" (no leading slash), falling back to "<root>".
    const raw = err.instancePath.replace(/^\//, "");
    const path = raw === "" ? "<root>" : raw;
    return {
      severity: "error" as const,
      path,
      code: "schema",
      message: ajvMessage(err),
    };
  });
  // python sorts schema errors by absolute path.
  issues.sort((a, b) => (a.path < b.path ? -1 : a.path > b.path ? 1 : 0));
  return issues;
}

function ajvMessage(err: {
  keyword: string;
  message?: string;
  params: Record<string, unknown>;
}): string {
  // Keep Ajv's message but surface the missing-property name for required
  // errors so callers (and the missing-header test) can find it by substring.
  if (err.keyword === "required" && typeof err.params.missingProperty === "string") {
    return `must have required property '${err.params.missingProperty}'`;
  }
  return err.message ?? err.keyword;
}

// ---------------------------------------------------------------------------
// Semantic layer
// ---------------------------------------------------------------------------

function semanticIssues(data: Record<string, unknown>): ValidationIssue[] {
  const issues: ValidationIssue[] = [];

  let numQubits: number | undefined;
  const device = data.device;
  if (isObject(device) && typeof device.num_qubits === "number") {
    numQubits = device.num_qubits;
  }

  for (const [path, datum] of iterDatums(data)) {
    checkDatum(path, datum, issues);
  }

  for (const [path, ref] of iterQubitRefs(data)) {
    const m = QUBIT_RE.exec(ref);
    if (!m) {
      issues.push({
        severity: "error",
        path,
        code: "malformed_qubit_ref",
        message: `malformed qubit reference '${ref}' (expected $n)`,
      });
      continue;
    }
    if (typeof numQubits === "number" && Number.isInteger(numQubits) && Number(m[1]) >= numQubits) {
      issues.push({
        severity: "error",
        path,
        code: "qubit_ref_out_of_range",
        message: `qubit reference ${ref} out of range (num_qubits=${numQubits})`,
      });
    }
  }

  for (const [path, matrix] of iterConfusionMatrices(data)) {
    matrix.forEach((row, i) => {
      let total = 0;
      let bad = false;
      for (const x of row) {
        const n = typeof x === "number" ? x : Number(x);
        if (!Number.isFinite(n)) {
          bad = true;
          break;
        }
        total += n;
      }
      if (bad) {
        issues.push({
          severity: "error",
          path: `${path}/${i}`,
          code: "confusion_matrix_non_numeric",
          message: "non-numeric confusion-matrix entry",
        });
        return;
      }
      if (Math.abs(total - 1.0) > CM_ROW_TOLERANCE) {
        issues.push({
          severity: "error",
          path: `${path}/${i}`,
          code: "confusion_matrix_row_sum",
          message: `confusion-matrix row sums to ${total.toFixed(4)}, expected ~1`,
        });
      }
    });
  }

  return issues;
}

function checkDatum(
  path: string,
  datum: Record<string, unknown>,
  issues: ValidationIssue[],
): void {
  const unit = datum.unit;
  if (unit !== undefined && unit !== null && !SI_UNITS.has(String(unit))) {
    issues.push({
      severity: "error",
      path: `${path}/unit`,
      code: "non_si_unit",
      message: `non-SI unit '${String(unit)}' (allowed: [${SI_UNITS_SORTED.map((u) => `'${u}'`).join(", ")}])`,
    });
  }
  const hasStd = datum.std_error !== undefined && datum.std_error !== null;
  const hasMinus = datum.err_minus !== undefined && datum.err_minus !== null;
  const hasPlus = datum.err_plus !== undefined && datum.err_plus !== null;
  if (hasStd && (hasMinus || hasPlus)) {
    issues.push({
      severity: "error",
      path,
      code: "std_error_with_asymmetric",
      message: "std_error must not appear together with err_minus/err_plus",
    });
  }
  if (hasMinus !== hasPlus) {
    issues.push({
      severity: "error",
      path,
      code: "unpaired_err",
      message: "err_minus and err_plus must be provided together",
    });
  }
}

// ---------------------------------------------------------------------------
// Tree walkers
// ---------------------------------------------------------------------------

function isObject(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

function isDatum(obj: unknown): obj is Record<string, unknown> {
  return isObject(obj) && "value" in obj && "unit" in obj;
}

function* iterDatums(data: Record<string, unknown>): Generator<[string, Record<string, unknown>]> {
  function* walk(node: unknown, path: string): Generator<[string, Record<string, unknown>]> {
    if (isObject(node)) {
      if (isDatum(node)) {
        yield [path, node];
      }
      for (const [k, v] of Object.entries(node)) {
        if (path === "" && k === "extensions") continue;
        yield* walk(v, path ? `${path}/${k}` : k);
      }
    } else if (Array.isArray(node)) {
      for (let i = 0; i < node.length; i++) {
        yield* walk(node[i], `${path}/${i}`);
      }
    }
  }
  yield* walk(data, "");
}

function* iterQubitRefs(data: Record<string, unknown>): Generator<[string, string]> {
  const device = data.device;
  if (isObject(device)) {
    const labels = device.qubit_labels;
    if (isObject(labels)) {
      for (const key of Object.keys(labels)) {
        yield [`device/qubit_labels/${key}`, key];
      }
    }
    const enabled = device.enabled_qubits;
    if (Array.isArray(enabled)) {
      for (let i = 0; i < enabled.length; i++) {
        yield [`device/enabled_qubits/${i}`, String(enabled[i])];
      }
    }
    const coupling = device.coupling_map;
    if (Array.isArray(coupling)) {
      for (let i = 0; i < coupling.length; i++) {
        const pair = coupling[i];
        if (Array.isArray(pair)) {
          for (let j = 0; j < pair.length; j++) {
            yield [`device/coupling_map/${i}/${j}`, String(pair[j])];
          }
        }
      }
    }
  }

  const qubits = data.qubits;
  if (isObject(qubits)) {
    for (const key of Object.keys(qubits)) {
      yield [`qubits/${key}`, key];
    }
  }

  for (const section of ["gates", "defcals"] as const) {
    const entries = data[section];
    if (Array.isArray(entries)) {
      for (let i = 0; i < entries.length; i++) {
        const entry = entries[i];
        if (isObject(entry) && Array.isArray(entry.qubits)) {
          const qs = entry.qubits;
          for (let j = 0; j < qs.length; j++) {
            yield [`${section}/${i}/qubits/${j}`, String(qs[j])];
          }
        }
      }
    }
  }
}

function* iterConfusionMatrices(
  data: Record<string, unknown>,
): Generator<[string, unknown[][]]> {
  const qubits = data.qubits;
  if (isObject(qubits)) {
    for (const [key, props] of Object.entries(qubits)) {
      if (isObject(props)) {
        const ro = props.readout;
        if (isObject(ro) && Array.isArray(ro.confusion_matrix)) {
          yield [`qubits/${key}/readout/confusion_matrix`, ro.confusion_matrix as unknown[][]];
        }
      }
    }
  }
}
