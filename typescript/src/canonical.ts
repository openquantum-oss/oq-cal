// Canonical oq-cal JSON serialization.
//
// Mirrors python/src/oq_cal/io.py. The canonical form is:
//   * 2-space indent;
//   * null/undefined model fields omitted entirely (exclude-none);
//   * JSON null inside extensions is kept (verbatim payload, not a model field);
//   * keys in model declaration order (not sorted) for known sections/fields;
//     free-form maps (extensions, defcal params, aggregates.ops, qubit_labels,
//     the qubits map itself) keep their own insertion order;
//   * UTF-8 verbatim (JSON.stringify does not \uXXXX-escape printable
//     non-ASCII);
//   * a single trailing newline.
//
// Conformance bar: STRUCTURAL equality (parse both sides, deep-equal). Byte
// equality with the Python writer is best-effort only; JS and Python format
// some floats differently (e.g. 5120.0 vs 5120, 9.87e-6 vs 0.00000987), but
// those parse to identical numbers, so structural equality holds as long as the
// arithmetic that produced the values is identical (which it is: both use
// IEEE-754 doubles).

import type { OqCalDocument } from "./types.js";

// Field order per the pydantic model declaration order in python/src/oq_cal/models.py.
const DATUM_ORDER = [
  "value",
  "unit",
  "std_error",
  "err_minus",
  "err_plus",
  "median",
  "method",
  "metric",
  "status",
  "updated_at",
];
const HEADER_ORDER = ["name", "version"];
const DEVICE_ORDER = [
  "id",
  "vendor",
  "model",
  "num_qubits",
  "qubit_labels",
  "enabled_qubits",
  "coupling_map",
];
const SNAPSHOT_ORDER = ["id", "captured_at", "source", "source_schema"];
const CLASSIFIER_ORDER = ["type", "projection", "threshold", "status"];
const READOUT_ORDER = ["fidelity", "duration", "confusion_matrix", "classifier"];
const BENCHMARK_ORDER = ["protocol", "fidelity", "error", "qubits"];
const QUBIT_PROPS_ORDER = [
  "t1",
  "t2",
  "t2_echo",
  "frequency_01",
  "anharmonicity",
  "readout",
  "benchmarks",
];
const AGG_QUBITS_ORDER = ["t1", "t2", "t2_echo"];
const AGG_READOUT_ORDER = ["fidelity", "duration"];
const AGG_GATE_ORDER = ["fidelity", "error", "duration"];
const AGGREGATES_ORDER = ["qubits", "readout", "gates_1q", "gates_2q", "ops"];
const GATE_ENTRY_ORDER = [
  "name",
  "qubits",
  "fidelity",
  "error",
  "duration",
  "benchmarks",
];
const DEFCAL_ORDER = ["gate", "qubits", "params"];
const DOCUMENT_ORDER = [
  "oq-cal",
  "device",
  "snapshot",
  "aggregates",
  "qubits",
  "gates",
  "defcals",
  "extensions",
];

type Json = unknown;

function isPlainObject(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

// Reorder a known object's keys by `order`, dropping null/undefined, then
// append any extra keys (unknown source fields that round-tripped) in their
// existing order. Recurses with a per-subtree ordering map.
function ordered(
  obj: Record<string, unknown>,
  order: string[],
  childOrders: Record<string, string[] | "free" | "datum"> = {},
): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  const seen = new Set<string>();
  const emit = (key: string): void => {
    if (!(key in obj)) return;
    const val = obj[key];
    if (val === null || val === undefined) return;
    seen.add(key);
    out[key] = normalizeChild(key, val, childOrders);
  };
  for (const key of order) emit(key);
  // Preserve any extra keys not in the declared order (verbatim round-trip).
  for (const key of Object.keys(obj)) {
    if (!seen.has(key)) emit(key);
  }
  return out;
}

function normalizeChild(
  key: string,
  val: unknown,
  childOrders: Record<string, string[] | "free" | "datum">,
): Json {
  const spec = childOrders[key];
  if (spec === "datum") return orderDatum(val);
  if (spec === "free") return stripNulls(val);
  if (Array.isArray(spec)) {
    if (isPlainObject(val)) return ordered(val, spec);
    return stripNulls(val);
  }
  return stripNulls(val);
}

function orderDatum(val: unknown): Json {
  if (!isPlainObject(val)) return stripNulls(val);
  return ordered(val, DATUM_ORDER);
}

// Recursively drop null/undefined from free-form model maps (params, ops,
// labels) while preserving key insertion order.
function stripNulls(val: unknown): Json {
  if (Array.isArray(val)) return val.map((v) => stripNulls(v));
  if (isPlainObject(val)) {
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(val)) {
      if (v === null || v === undefined) continue;
      out[k] = stripNulls(v);
    }
    return out;
  }
  return val;
}

// Extensions are a verbatim source payload. JSON null is data, so it stays.
// undefined is not JSON and is dropped.
function preserveNulls(val: unknown): Json {
  if (Array.isArray(val)) return val.map((v) => preserveNulls(v));
  if (isPlainObject(val)) {
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(val)) {
      if (v === undefined) continue;
      out[k] = v === null ? null : preserveNulls(v);
    }
    return out;
  }
  return val;
}

function canonicalizeDatumMap(val: unknown): Json {
  // For maps whose values are datums (aggregates.ops), order each datum.
  if (!isPlainObject(val)) return stripNulls(val);
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(val)) {
    if (v === null || v === undefined) continue;
    out[k] = orderDatum(v);
  }
  return out;
}

function canonicalizeReadout(val: unknown): Json {
  if (!isPlainObject(val)) return stripNulls(val);
  return ordered(val, READOUT_ORDER, {
    fidelity: "datum",
    duration: "datum",
    confusion_matrix: "free",
    classifier: CLASSIFIER_ORDER,
  });
}

function canonicalizeBenchmark(val: unknown): Json {
  if (!isPlainObject(val)) return stripNulls(val);
  return ordered(val, BENCHMARK_ORDER, { fidelity: "datum", error: "datum" });
}

function canonicalizeQubitProps(val: unknown): Json {
  if (!isPlainObject(val)) return stripNulls(val);
  const out = ordered(val, QUBIT_PROPS_ORDER, {
    t1: "datum",
    t2: "datum",
    t2_echo: "datum",
    frequency_01: "datum",
    anharmonicity: "datum",
  });
  if (isPlainObject(out) && out.readout !== undefined) {
    out.readout = canonicalizeReadout(val.readout);
  }
  if (Array.isArray(out.benchmarks)) {
    out.benchmarks = (val.benchmarks as unknown[]).map(canonicalizeBenchmark);
  }
  return out;
}

function canonicalizeAggregates(val: unknown): Json {
  if (!isPlainObject(val)) return stripNulls(val);
  const out: Record<string, unknown> = {};
  for (const key of AGGREGATES_ORDER) {
    const v = val[key];
    if (v === null || v === undefined) continue;
    if (key === "qubits") {
      out[key] = ordered(v as Record<string, unknown>, AGG_QUBITS_ORDER, {
        t1: "datum",
        t2: "datum",
        t2_echo: "datum",
      });
    } else if (key === "readout") {
      out[key] = ordered(v as Record<string, unknown>, AGG_READOUT_ORDER, {
        fidelity: "datum",
        duration: "datum",
      });
    } else if (key === "gates_1q" || key === "gates_2q") {
      out[key] = ordered(v as Record<string, unknown>, AGG_GATE_ORDER, {
        fidelity: "datum",
        error: "datum",
        duration: "datum",
      });
    } else if (key === "ops") {
      out[key] = canonicalizeDatumMap(v);
    }
  }
  // extra keys
  for (const [k, v] of Object.entries(val)) {
    if (AGGREGATES_ORDER.includes(k)) continue;
    if (v === null || v === undefined) continue;
    out[k] = stripNulls(v);
  }
  return out;
}

function canonicalizeDocument(doc: OqCalDocument): Record<string, unknown> {
  const d = doc as unknown as Record<string, unknown>;
  const out: Record<string, unknown> = {};
  const seen = new Set<string>();
  const put = (key: string, value: unknown): void => {
    if (value === null || value === undefined) return;
    seen.add(key);
    out[key] = value;
  };

  for (const key of DOCUMENT_ORDER) {
    const v = d[key];
    if (v === null || v === undefined) continue;
    switch (key) {
      case "oq-cal":
        put(key, ordered(v as Record<string, unknown>, HEADER_ORDER));
        break;
      case "device":
        put(key, ordered(v as Record<string, unknown>, DEVICE_ORDER, {
          qubit_labels: "free",
          enabled_qubits: "free",
          coupling_map: "free",
        }));
        break;
      case "snapshot":
        put(key, ordered(v as Record<string, unknown>, SNAPSHOT_ORDER));
        break;
      case "aggregates":
        put(key, canonicalizeAggregates(v));
        break;
      case "qubits": {
        const qm = v as Record<string, unknown>;
        const outQ: Record<string, unknown> = {};
        for (const [ref, props] of Object.entries(qm)) {
          if (props === null || props === undefined) continue;
          outQ[ref] = canonicalizeQubitProps(props);
        }
        put(key, outQ);
        break;
      }
      case "gates":
        put(
          key,
          (v as unknown[]).map((g) => {
            if (!isPlainObject(g)) return stripNulls(g);
            const og = ordered(g, GATE_ENTRY_ORDER, {
              fidelity: "datum",
              error: "datum",
              duration: "datum",
              qubits: "free",
            });
            if (Array.isArray(og.benchmarks)) {
              og.benchmarks = (g.benchmarks as unknown[]).map(canonicalizeBenchmark);
            }
            return og;
          }),
        );
        break;
      case "defcals":
        put(
          key,
          (v as unknown[]).map((dc) => {
            if (!isPlainObject(dc)) return stripNulls(dc);
            return ordered(dc, DEFCAL_ORDER, { qubits: "free", params: "free" });
          }),
        );
        break;
      case "extensions":
        put(key, preserveNulls(v));
        break;
    }
  }
  // Any extra top-level keys (additionalProperties on the document).
  for (const [k, v] of Object.entries(d)) {
    if (seen.has(k) || DOCUMENT_ORDER.includes(k)) continue;
    if (v === null || v === undefined) continue;
    out[k] = stripNulls(v);
  }
  return out;
}

/**
 * Serialize an oq-cal document to the canonical JSON string (2-space indent,
 * model field order, null/undefined omitted, single trailing newline).
 */
export function toCanonicalJson(doc: OqCalDocument): string {
  const canonical = canonicalizeDocument(doc);
  return JSON.stringify(canonical, null, 2) + "\n";
}
