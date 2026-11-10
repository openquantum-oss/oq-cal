// Importer for AWS Braket Rigetti device capabilities (schema v2).
// Behavior-identical port of python/src/oq_cal/importers/rigetti.py.
// Capabilities carry connectivity and optional pulse frames. Calibration is
// taken only from an embedded standardized-properties block. Ports stay in
// extensions. This importer does not invent T1 or gate errors. When
// provider.specs repeats a standardized T1 or T2 and that block omitted the
// standard error, the specs error is copied onto the datum.

import type { OqCalDocument } from "../types.js";
import { BraketSchemaError, fromBraketStandardized } from "./braket.js";

export const RIGETTI_SCHEMA = "braket.device_schema.rigetti.rigetti_device_capabilities";

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
  iswap: "iswap",
  xy: "xy",
};

type Obj = Record<string, unknown>;

function isObj(v: unknown): v is Obj {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

function asInt(value: unknown): number | null {
  if (typeof value === "number" && Number.isInteger(value)) return value;
  if (typeof value === "string" && /^[0-9]+$/.test(value)) return parseInt(value, 10);
  return null;
}

export interface RigettiOptions {
  numQubits?: number;
  deviceId?: string;
  vendor?: string;
  model?: string;
  capturedAt?: string;
  snapshotId?: string;
}

function collectIndices(payload: Obj): Set<number> {
  const indices = new Set<number>();
  const paradigm = isObj(payload.paradigm) ? payload.paradigm : {};
  const connectivity = isObj(paradigm.connectivity) ? paradigm.connectivity : {};
  const graph = connectivity.connectivityGraph;
  if (isObj(graph)) {
    for (const [rawSrc, rawDsts] of Object.entries(graph)) {
      const src = asInt(rawSrc);
      if (src !== null) indices.add(src);
      if (Array.isArray(rawDsts)) {
        for (const rawDst of rawDsts) {
          const dst = asInt(rawDst);
          if (dst !== null) indices.add(dst);
        }
      }
    }
  }
  const pulse = isObj(payload.pulse) ? payload.pulse : {};
  const frames = pulse.frames;
  if (isObj(frames)) {
    for (const frame of Object.values(frames)) {
      if (!isObj(frame) || !Array.isArray(frame.qubitMappings)) continue;
      for (const qubit of frame.qubitMappings) {
        const idx = asInt(qubit);
        if (idx !== null) indices.add(idx);
      }
    }
  }
  const standardized = payload.standardized;
  if (isObj(standardized)) {
    const one = isObj(standardized.oneQubitProperties) ? standardized.oneQubitProperties : {};
    for (const key of Object.keys(one)) {
      const idx = asInt(key);
      if (idx !== null) indices.add(idx);
    }
    const two = isObj(standardized.twoQubitProperties) ? standardized.twoQubitProperties : {};
    for (const key of Object.keys(two)) {
      for (const part of key.split("-")) {
        const idx = asInt(part);
        if (idx !== null) indices.add(idx);
      }
    }
  }
  return indices;
}

function shiftStandardized(standardized: Obj, shift: number): Obj {
  if (shift === 0) return standardized;
  const one: Obj = {};
  const oneSrc = isObj(standardized.oneQubitProperties) ? standardized.oneQubitProperties : {};
  for (const [key, value] of Object.entries(oneSrc)) {
    const idx = asInt(key);
    if (idx !== null) one[String(idx - shift)] = value;
  }
  const two: Obj = {};
  const twoSrc = isObj(standardized.twoQubitProperties) ? standardized.twoQubitProperties : {};
  for (const [key, value] of Object.entries(twoSrc)) {
    const parts: string[] = [];
    let ok = true;
    for (const part of key.split("-")) {
      const idx = asInt(part);
      if (idx === null) {
        ok = false;
        break;
      }
      parts.push(String(idx - shift));
    }
    if (ok) two[parts.join("-")] = value;
  }
  return { ...standardized, oneQubitProperties: one, twoQubitProperties: two };
}

function graphEdges(payload: Obj, shift: number): Array<[number, number]> {
  const paradigm = isObj(payload.paradigm) ? payload.paradigm : {};
  const connectivity = isObj(paradigm.connectivity) ? paradigm.connectivity : {};
  const graph = connectivity.connectivityGraph;
  const edges: Array<[number, number]> = [];
  if (!isObj(graph)) return edges;
  for (const [rawSrc, rawDsts] of Object.entries(graph)) {
    const src = asInt(rawSrc);
    if (src === null || !Array.isArray(rawDsts)) continue;
    for (const rawDst of rawDsts) {
      const dst = asInt(rawDst);
      if (dst === null || dst === src) continue;
      edges.push([src - shift, dst - shift]);
    }
  }
  return edges;
}

function pulseDefcals(payload: Obj, shift: number): Obj[] {
  const pulse = isObj(payload.pulse) ? payload.pulse : {};
  const frames = pulse.frames;
  if (!isObj(frames)) return [];
  const defcals: Obj[] = [];
  for (const frame of Object.values(frames)) {
    if (!isObj(frame)) continue;
    const frequency = frame.frequency;
    const gate = frame.associatedGate;
    const mappings = frame.qubitMappings;
    if (typeof frequency !== "number" || typeof gate !== "string" || !gate) continue;
    if (!Array.isArray(mappings) || mappings.length === 0) continue;
    const qubits: string[] = [];
    let ok = true;
    for (const mapping of mappings) {
      const idx = asInt(mapping);
      if (idx === null) {
        ok = false;
        break;
      }
      qubits.push(`$${idx - shift}`);
    }
    if (!ok) continue;
    defcals.push({
      gate: GATE_NAME[gate.toLowerCase()] ?? gate.toLowerCase(),
      qubits,
      params: { frequency_hz: frequency },
    });
  }
  defcals.sort((a, b) => {
    const ag = String(a.gate);
    const bg = String(b.gate);
    if (ag !== bg) return ag < bg ? -1 : 1;
    const aq = (a.qubits as string[]).join(",");
    const bq = (b.qubits as string[]).join(",");
    if (aq !== bq) return aq < bq ? -1 : 1;
    return Number((a.params as Obj).frequency_hz) - Number((b.params as Obj).frequency_hz);
  });
  return defcals;
}

function fillSpecsStandardErrors(doc: Obj, payload: Obj, shift: number): void {
  const qubits = isObj(doc.qubits) ? doc.qubits : null;
  if (!qubits) return;
  const provider = isObj(payload.provider) ? payload.provider : {};
  const specs = isObj(provider.specs) ? provider.specs : {};
  const benchmarks = Array.isArray(specs.benchmarks) ? specs.benchmarks : [];
  const fields: Record<string, readonly [string, string]> = {
    FreeInversionRecovery: ["t1", "T1"],
    FreeInductionDecay: ["t2", "T2"],
  };
  for (const bench of benchmarks) {
    if (!isObj(bench)) continue;
    const mapped = fields[String(bench.name)];
    if (!mapped) continue;
    const [field, characteristic] = mapped;
    const sites = Array.isArray(bench.sites) ? bench.sites : [];
    for (const site of sites) {
      if (!isObj(site)) continue;
      const siteNodes = Array.isArray(site.node_ids) ? site.node_ids : [];
      const entries = Array.isArray(site.characteristics) ? site.characteristics : [];
      for (const entry of entries) {
        if (!isObj(entry) || entry.name !== characteristic) continue;
        const nodeIds = Array.isArray(entry.node_ids) ? entry.node_ids : siteNodes;
        if (nodeIds.length !== 1) continue;
        const index = asInt(nodeIds[0]);
        const value = entry.value;
        const error = entry.error;
        if (index === null || typeof value !== "number" || typeof error !== "number") continue;
        if (error <= 0) continue;
        const props = qubits[`$${index - shift}`];
        if (!isObj(props)) continue;
        const datum = props[field];
        if (!isObj(datum) || datum.std_error !== undefined) continue;
        if (typeof datum.value !== "number") continue;
        const tolerance = Math.max(1e-18, 1e-9 * Math.abs(value));
        if (Math.abs(datum.value - value) > tolerance) continue;
        datum.std_error = error;
      }
    }
  }
}

export function fromBraketRigetti(payload: object, opts: RigettiOptions = {}): OqCalDocument {
  const p = payload as Obj;
  const header = isObj(p.braketSchemaHeader) ? p.braketSchemaHeader : {};
  if (header.name !== RIGETTI_SCHEMA) {
    throw new BraketSchemaError(
      `unsupported Braket schema ${JSON.stringify(header.name)}; expected ${JSON.stringify(RIGETTI_SCHEMA)}`,
    );
  }
  const version = String(header.version ?? "");
  if (version !== "2") {
    throw new BraketSchemaError(
      `unsupported ${RIGETTI_SCHEMA} version ${JSON.stringify(version)}; supported: 2`,
    );
  }

  const indices = collectIndices(p);
  const shift = !indices.has(0) && indices.has(1) ? 1 : 0;
  const standardized = p.standardized;
  const doc: Obj = isObj(standardized)
    ? (fromBraketStandardized(shiftStandardized(standardized, shift)) as unknown as Obj)
    : {
        "oq-cal": { name: "oq-cal.device_calibration", version: "0.1" },
        device: { id: "braket-device" },
        snapshot: { source: "aws-braket" },
      };

  const device = doc.device as Obj;
  const paradigm = isObj(p.paradigm) ? p.paradigm : {};
  const counts: number[] = [];
  if (typeof paradigm.qubitCount === "number") counts.push(paradigm.qubitCount);
  if (indices.size > 0) counts.push(Math.max(...indices) - shift + 1);
  if (typeof device.num_qubits === "number") counts.push(device.num_qubits);
  if (opts.numQubits !== undefined) counts.push(opts.numQubits);
  if (counts.length > 0) device.num_qubits = Math.max(...counts);

  const edges = graphEdges(p, shift);
  if (edges.length > 0) {
    const unique = new Map<string, [number, number]>();
    for (const edge of edges) unique.set(`${edge[0]},${edge[1]}`, edge);
    const sorted = [...unique.values()].sort((a, b) => a[0] - b[0] || a[1] - b[1]);
    device.coupling_map = sorted.map(([i, j]) => [`$${i}`, `$${j}`]);
  }
  if (shift && indices.size > 0) {
    const labels: Record<string, string> = {};
    for (const idx of [...indices].sort((a, b) => a - b)) labels[`$${idx - shift}`] = String(idx);
    device.qubit_labels = labels;
  }

  const defcals = pulseDefcals(p, shift);
  if (defcals.length > 0) {
    const existing = Array.isArray(doc.defcals) ? (doc.defcals as Obj[]) : [];
    doc.defcals = existing.concat(defcals);
  }
  fillSpecsStandardErrors(doc, p, shift);

  const snapshot = doc.snapshot as Obj;
  const service = isObj(p.service) ? p.service : {};
  if (typeof service.updatedAt === "string") snapshot.captured_at = service.updatedAt;
  snapshot.source = "aws-braket";
  snapshot.source_schema = `${RIGETTI_SCHEMA} v2`;
  doc.extensions = { braket: payload };

  if (opts.deviceId !== undefined) device.id = opts.deviceId;
  if (opts.vendor !== undefined) device.vendor = opts.vendor;
  if (opts.model !== undefined) device.model = opts.model;
  if (opts.capturedAt !== undefined) snapshot.captured_at = opts.capturedAt;
  if (opts.snapshotId !== undefined) snapshot.id = opts.snapshotId;

  return doc as unknown as OqCalDocument;
}
