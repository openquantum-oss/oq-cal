// Importer for AWS Braket standardized gate-model QPU device properties
// (schema versions 1 and 3). Behavior-identical port of
// python/src/oq_cal/importers/braket.py.

import type { Datum, OqCalDocument } from "../types.js";

export const SCHEMA_NAME =
  "braket.device_schema.standardized_gate_model_qpu_device_properties";

const FIDELITY_METHOD: Record<string, string> = {
  RANDOMIZED_BENCHMARKING: "rb",
  SIMULTANEOUS_RANDOMIZED_BENCHMARKING: "simultaneous_rb",
  INTERLEAVED_RANDOMIZED_BENCHMARKING: "interleaved_rb",
  SIMULTANEOUS_INTERLEAVED_RANDOMIZED_BENCHMARKING: "simultaneous_interleaved_rb",
  READOUT: "readout",
};

const GATE_NAME: Record<string, string> = {
  cz: "cz",
  cx: "cx",
  cnot: "cx",
  x: "x",
  y: "y",
  z: "z",
  h: "h",
  s: "s",
  sx: "sx",
  rx: "rx",
  ry: "ry",
  rz: "rz",
  swap: "swap",
  ccx: "ccx",
  x90: "sx",
  cphase: "cz",
};

const BENCHMARK_GATE_NAMES = new Set(["two_qubit_clifford", "one_qubit_clifford", "clifford"]);

export class BraketSchemaError extends Error {}

type Obj = Record<string, unknown>;

function isObj(v: unknown): v is Obj {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

function num(v: unknown): number {
  return typeof v === "number" ? v : Number(v);
}

// ---------------------------------------------------------------------------
// Unit / datum helpers
// ---------------------------------------------------------------------------

function toSeconds(value: number, unit: string | undefined): [number, string] {
  const u = (unit ?? "").toLowerCase();
  if (u === "s" || u === "") return [value, "s"];
  if (["us", "µs", "microsecond", "microseconds"].includes(u)) return [value * 1e-6, "s"];
  if (["ms", "millisecond", "milliseconds"].includes(u)) return [value * 1e-3, "s"];
  if (["ns", "nanosecond", "nanoseconds"].includes(u)) return [value * 1e-9, "s"];
  return [value, "s"];
}

function timeDatum(entry: Obj, extra: Partial<Datum> = {}): Datum {
  const rawValue = num(entry.value);
  const [value] = toSeconds(rawValue, entry.unit as string | undefined);
  const d: Datum = { value, unit: "s" };
  const se = entry.standardError;
  if (se) {
    const factor = rawValue ? value / rawValue : 1.0;
    d.std_error = num(se) * factor;
  }
  Object.assign(d, extra);
  return d;
}

// Braket marks a dead / uncalibrated qubit or edge with the exact numeric pair
// fidelity == 0.5 AND standardError == 1 on the parsed JSON numbers.
function isSentinel(entry: Obj): boolean {
  return entry.fidelity === 0.5 && entry.standardError === 1;
}

function fidelityDatum(entry: Obj, metric?: string): Datum {
  const d: Datum = { value: num(entry.fidelity), unit: "dimensionless" };
  // READOUT names the quantity. RB names a protocol, not average vs process
  // fidelity, so those entries leave metric unset.
  if (metric) d.metric = metric;
  if (isSentinel(entry)) {
    // Sentinel datum: keep value 0.5, DROP std_error (it is a marker, not a
    // measurement), flag status "unmeasured" for downstream exclusion.
    d.status = "unmeasured";
    if (entry.median !== undefined && entry.median !== null) d.median = num(entry.median);
    const ftype0 = isObj(entry.fidelityType) ? entry.fidelityType : {};
    const name0 = ftype0.name as string | undefined;
    if (name0) {
      const method0 = FIDELITY_METHOD[name0];
      if (method0) d.method = method0;
    }
    return d;
  }
  const se = entry.standardError;
  if (se) d.std_error = num(se);
  if (entry.median !== undefined && entry.median !== null) d.median = num(entry.median);
  const ftype = isObj(entry.fidelityType) ? entry.fidelityType : {};
  const name = ftype.name as string | undefined;
  if (name) {
    const method = FIDELITY_METHOD[name];
    if (method) d.method = method;
  }
  return d;
}

// ---------------------------------------------------------------------------
// Per-qubit (v1 + mixed v3)
// ---------------------------------------------------------------------------

function buildQubit(props: Obj): Obj {
  const qp: Obj = {};
  if ("T1" in props) qp.t1 = timeDatum(props.T1 as Obj);
  if ("T2" in props) qp.t2 = timeDatum(props.T2 as Obj);

  const readout: Obj = {};
  const benchmarks: Obj[] = [];
  let e01: number | null = null;
  let e10: number | null = null;

  for (const entry of (props.oneQubitFidelity as unknown[]) ?? []) {
    if (!isObj(entry)) continue;
    const ftype = (isObj(entry.fidelityType) ? entry.fidelityType.name : undefined) as
      | string
      | undefined;
    if (ftype === "READOUT") {
      readout.fidelity = fidelityDatum(entry, "readout_fidelity");
    } else if (ftype === "READOUT_ERROR_0_TO_1") {
      e01 = num(entry.fidelity);
    } else if (ftype === "READOUT_ERROR_1_TO_0") {
      e10 = num(entry.fidelity);
    } else {
      benchmarks.push(benchmarkFromEntry(entry, null));
    }
  }

  if (e01 !== null || e10 !== null) {
    const a = e01 ?? 0.0;
    const b = e10 ?? 0.0;
    readout.confusion_matrix = [
      [1.0 - a, a],
      [b, 1.0 - b],
    ];
  }

  if (Object.keys(readout).length > 0) qp.readout = readout;
  if (benchmarks.length > 0) qp.benchmarks = benchmarks;
  return qp;
}

function benchmarkFromEntry(entry: Obj, qubits: string[] | null): Obj {
  const ftype = (isObj(entry.fidelityType) ? entry.fidelityType.name : undefined) as
    | string
    | undefined;
  const protocol = FIDELITY_METHOD[ftype ?? ""] ?? (ftype ?? "benchmark").toLowerCase();
  const bm: Obj = { protocol };
  bm.fidelity = fidelityDatum(entry);
  if (qubits) bm.qubits = qubits;
  return bm;
}

// ---------------------------------------------------------------------------
// Per-pair (v1)
// ---------------------------------------------------------------------------

function pairQubits(key: string, shift: number): string[] {
  return key.split("-").map((p) => `$${parseInt(p, 10) - shift}`);
}

// Emit DIRECTED coupling-map pairs (both directions) from undirected pairs,
// sorted numerically by (i, j).
function couplingMap(pairs: Set<string>): string[][] {
  const directed = new Set<string>();
  for (const p of pairs) {
    const [i, j] = p.split(",").map((x) => parseInt(x, 10));
    directed.add(`${i},${j}`);
    directed.add(`${j},${i}`);
  }
  const tuples = [...directed].map((p) => p.split(",").map((x) => parseInt(x, 10)) as [number, number]);
  tuples.sort((a, b) => (a[0] !== b[0] ? a[0] - b[0] : a[1] - b[1]));
  return tuples.map(([i, j]) => [`$${i}`, `$${j}`]);
}

function buildPairGates(key: string, props: Obj, shift: number): Obj[] {
  const qubits = pairQubits(key, shift);
  const gates: Obj[] = [];
  const benchmarks: Obj[] = [];
  for (const entry of (props.twoQubitGateFidelity as unknown[]) ?? []) {
    if (!isObj(entry)) continue;
    const rawName = (entry.gateName as string) ?? "";
    const norm = rawName.toLowerCase();
    if (BENCHMARK_GATE_NAMES.has(norm)) {
      const bm = benchmarkFromEntry(entry, qubits);
      bm.protocol = norm;
      benchmarks.push(bm);
      continue;
    }
    const name = GATE_NAME[norm] ?? norm;
    const ge: Obj = { name, qubits };
    ge.fidelity = fidelityDatum(entry);
    gates.push(ge);
  }
  if (benchmarks.length > 0) {
    if (gates.length > 0) {
      gates[0]!.benchmarks = benchmarks;
    } else {
      gates.push({ name: "benchmark", qubits, benchmarks });
    }
  }
  return gates;
}

// ---------------------------------------------------------------------------
// Aggregates (v3)
// ---------------------------------------------------------------------------

function firstFidelity(entries: unknown, metric?: string): Datum | null {
  if (!Array.isArray(entries) || entries.length === 0) return null;
  const first = entries[0];
  return isObj(first) ? fidelityDatum(first, metric) : null;
}

// The field name is a readout fidelity only when the entry does not name a
// different protocol. An absent fidelityType (AQT) or READOUT names the
// quantity. IonQ types the same field RANDOMIZED_BENCHMARKING, which is a
// protocol, so metric stays unset and method stays "rb".
function readoutAggregateMetric(entries: unknown): string | undefined {
  if (!Array.isArray(entries) || entries.length === 0 || !isObj(entries[0])) return undefined;
  const ftype = isObj(entries[0].fidelityType)
    ? (entries[0].fidelityType.name as string | undefined)
    : undefined;
  if (ftype === undefined || ftype === "READOUT") return "readout_fidelity";
  return undefined;
}

function buildAggregates(payload: Obj): Obj | null {
  const agg: Obj = {};

  const aq: Obj = {};
  if ("T1" in payload) aq.t1 = timeDatum(payload.T1 as Obj);
  if ("T2" in payload) aq.t2 = timeDatum(payload.T2 as Obj);
  if (Object.keys(aq).length > 0) agg.qubits = aq;

  const ar: Obj = {};
  const rf = firstFidelity(
    payload.readoutFidelity,
    readoutAggregateMetric(payload.readoutFidelity),
  );
  if (rf !== null) ar.fidelity = rf;
  if ("readoutDuration" in payload) ar.duration = timeDatum(payload.readoutDuration as Obj);
  if (Object.keys(ar).length > 0) agg.readout = ar;

  const g1: Obj = {};
  const f1 = firstFidelity(payload.singleQubitFidelity);
  if (f1 !== null) g1.fidelity = f1;
  if ("singleQubitGateDuration" in payload)
    g1.duration = timeDatum(payload.singleQubitGateDuration as Obj);
  if (Object.keys(g1).length > 0) agg.gates_1q = g1;

  const g2: Obj = {};
  const f2 = firstFidelity(payload.twoQubitGateFidelity);
  if (f2 !== null) g2.fidelity = f2;
  if ("twoQubitGateDuration" in payload)
    g2.duration = timeDatum(payload.twoQubitGateDuration as Obj);
  if (Object.keys(g2).length > 0) agg.gates_2q = g2;

  if ("activeResetDuration" in payload) {
    agg.ops = { reset_duration: timeDatum(payload.activeResetDuration as Obj) };
  }

  if (Object.keys(agg).length > 0) return agg;
  return null;
}

// ---------------------------------------------------------------------------
// Entry point
// ---------------------------------------------------------------------------

export interface BraketOptions {
  numQubits?: number;
  // Convert-time identity / provenance. A supplied value OVERRIDES whatever the
  // importer derives from the source; omitting it leaves current behavior.
  deviceId?: string;
  vendor?: string;
  model?: string;
  capturedAt?: string;
  snapshotId?: string;
}

export function fromBraketStandardized(payload: object, opts: BraketOptions = {}): OqCalDocument {
  const p = payload as Obj;
  const header = isObj(p.braketSchemaHeader) ? p.braketSchemaHeader : {};
  if (header.name !== SCHEMA_NAME) {
    throw new BraketSchemaError(
      `unsupported Braket schema ${JSON.stringify(header.name)}; expected ${JSON.stringify(SCHEMA_NAME)}`,
    );
  }
  const version = String(header.version ?? "");
  if (version !== "1" && version !== "3") {
    throw new BraketSchemaError(
      `unsupported ${SCHEMA_NAME} version ${JSON.stringify(version)}; supported: 1, 3`,
    );
  }

  const oneQubit = isObj(p.oneQubitProperties) ? p.oneQubitProperties : {};
  const twoQubit = isObj(p.twoQubitProperties) ? p.twoQubitProperties : {};

  // 1-based detection. oq-cal $n indices are ALWAYS 0-based (spec section 4). Some
  // vendors (notably IQM on Braket) number qubits from 1. Collect every source
  // index appearing in oneQubitProperties keys and twoQubitProperties pair keys:
  // if index 0 appears nowhere AND index 1 appears, the source is 1-based and
  // every index is shifted down by 1. Otherwise indices are kept verbatim,
  // INCLUDING gaps (an already-0-based sparse payload stays sparse; never densify).
  const sourceIndices = new Set<number>();
  for (const key of Object.keys(oneQubit)) sourceIndices.add(parseInt(key, 10));
  for (const key of Object.keys(twoQubit)) {
    for (const part of key.split("-")) sourceIndices.add(parseInt(part, 10));
  }
  const shift = !sourceIndices.has(0) && sourceIndices.has(1) ? 1 : 0;

  // qubits (shifted keys)
  const qubits: Record<string, Obj> = {};
  for (const [key, props] of Object.entries(oneQubit)) {
    if (!isObj(props)) continue;
    const qp = buildQubit(props);
    if (Object.keys(qp).length > 0) qubits[`$${parseInt(key, 10) - shift}`] = qp;
  }

  // gates (per-pair, v1); pair evidence carries post-shift indices
  const gates: Obj[] = [];
  const pairEvidence = new Set<string>();
  for (const [key, props] of Object.entries(twoQubit)) {
    if (!isObj(props)) continue;
    gates.push(...buildPairGates(key, props, shift));
    const parts = key.split("-");
    if (parts.length === 2) {
      // Braket v1 pair keys are undirected (IQM CZ is bidirectional).
      pairEvidence.add(`${parseInt(parts[0]!, 10) - shift},${parseInt(parts[1]!, 10) - shift}`);
    }
  }

  // aggregates (v3 device level)
  const aggregates = buildAggregates(p);

  // num_qubits inference (post-shift)
  let inferred: number | null = null;
  if (sourceIndices.size > 0) inferred = Math.max(...sourceIndices) - shift + 1;

  let nq: number | undefined;
  if (inferred !== null && opts.numQubits !== undefined) nq = Math.max(inferred, opts.numQubits);
  else if (inferred !== null) nq = inferred;
  else if (opts.numQubits !== undefined) nq = opts.numQubits;
  else nq = undefined;

  const snapshot: Obj = {
    source: "aws-braket",
    source_schema: `${SCHEMA_NAME} v${version}`,
  };
  if (p.updatedAt) snapshot.captured_at = p.updatedAt;
  // Identity / provenance overrides (win over any source-derived value).
  if (opts.snapshotId !== undefined) snapshot.id = opts.snapshotId;
  if (opts.capturedAt !== undefined) snapshot.captured_at = opts.capturedAt;

  // Braket payloads carry no device identity: "braket-device" is a last-resort
  // fallback, used only when the caller supplies no deviceId.
  const device: Obj = { id: opts.deviceId ?? "braket-device" };
  if (nq !== undefined) device.num_qubits = nq;
  if (opts.vendor !== undefined) device.vendor = opts.vendor;
  if (opts.model !== undefined) device.model = opts.model;
  if (shift) {
    // A shift was applied: record the original vendor numbering so the bridge
    // from 0-based $n back to the source keys is never lost ("$0" -> "1", ...).
    const labels: Record<string, string> = {};
    for (const idx of [...sourceIndices].sort((a, b) => a - b)) {
      labels[`$${idx - shift}`] = String(idx);
    }
    device.qubit_labels = labels;
  }
  if (pairEvidence.size > 0) device.coupling_map = couplingMap(pairEvidence);

  const doc: Obj = {
    "oq-cal": { name: "oq-cal.device_calibration", version: "0.1" },
    device,
    snapshot,
    extensions: { braket: payload },
  };
  if (aggregates !== null) doc.aggregates = aggregates;
  if (Object.keys(qubits).length > 0) doc.qubits = qubits;
  if (gates.length > 0) doc.gates = gates;

  return orderDocumentKeys(doc) as unknown as OqCalDocument;
}

// Reassemble the top-level object in canonical section order so the raw
// importer output matches the python model's section order (aesthetic; the
// canonical writer re-orders anyway, but this keeps intermediate objects tidy).
function orderDocumentKeys(doc: Obj): Obj {
  const order = [
    "oq-cal",
    "device",
    "snapshot",
    "aggregates",
    "qubits",
    "gates",
    "defcals",
    "extensions",
  ];
  const out: Obj = {};
  for (const k of order) if (k in doc) out[k] = doc[k];
  for (const k of Object.keys(doc)) if (!(k in out)) out[k] = doc[k];
  return out;
}
