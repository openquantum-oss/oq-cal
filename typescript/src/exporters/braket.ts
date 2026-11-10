// Export an oq-cal document to an AWS Braket device dict.
// toBraket writes Rigetti capabilities v2 when snapshot.source_schema names
// that schema, and standardized properties v1 otherwise.
// Behavior-identical port of python/src/oq_cal/exporters/braket.py.

import type { OqCalDocument } from "../types.js";

type Obj = Record<string, unknown>;

const SCHEMA_NAME = "braket.device_schema.standardized_gate_model_qpu_device_properties";
const SCHEMA_VERSION = "1";
const RIGETTI_SCHEMA = "braket.device_schema.rigetti.rigetti_device_capabilities";
const PARADIGM_SCHEMA = "braket.device_schema.gate_model_qpu_paradigm_properties";

const FIDELITY_TYPE: Record<string, string> = {
  rb: "RANDOMIZED_BENCHMARKING",
  randomized_benchmarking: "RANDOMIZED_BENCHMARKING",
  simultaneous_rb: "SIMULTANEOUS_RANDOMIZED_BENCHMARKING",
  interleaved_rb: "INTERLEAVED_RANDOMIZED_BENCHMARKING",
  direct_rb: "RANDOMIZED_BENCHMARKING",
  readout: "READOUT",
};

const NOT_READOUT = new Set([
  "average_gate_fidelity",
  "process_fidelity",
  "state_fidelity",
  "rb_decay",
  "assignment_error",
  "average_gate_error",
]);

function isObj(v: unknown): v is Obj {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

function qubitIndex(ref: unknown): number | null {
  if (typeof ref === "string" && ref.startsWith("$") && /^[0-9]+$/.test(ref.slice(1))) {
    return parseInt(ref.slice(1), 10);
  }
  return null;
}

function coherence(datum: unknown): Obj | null {
  if (!isObj(datum)) return null;
  const out: Obj = { value: datum.value, unit: "S" };
  if (datum.std_error !== undefined && datum.std_error !== null) {
    out.standardError = datum.std_error;
  }
  return out;
}

function fidelityType(method: unknown, metric: unknown, onReadout = false): string | null {
  if (typeof method === "string" && method in FIDELITY_TYPE) return FIDELITY_TYPE[method]!;
  if (metric === "readout_fidelity") return "READOUT";
  if (onReadout && (typeof metric !== "string" || !NOT_READOUT.has(metric))) return "READOUT";
  return null;
}

function fidelityEntry(value: unknown, ftype: string, stdError: unknown): Obj {
  const entry: Obj = { fidelityType: { name: ftype }, fidelity: value };
  if (stdError !== undefined && stdError !== null) entry.standardError = stdError;
  return entry;
}

function oneQubitFidelity(props: Obj): Obj[] {
  const entries: Obj[] = [];

  const ro = props.readout;
  if (isObj(ro) && isObj(ro.fidelity)) {
    const fid = ro.fidelity;
    const ftype = fidelityType(fid.method, fid.metric, true);
    if (ftype !== null) entries.push(fidelityEntry(fid.value, ftype, fid.std_error));
    const cm = ro.confusion_matrix;
    if (
      Array.isArray(cm) &&
      cm.length === 2 &&
      cm.every((r) => Array.isArray(r) && r.length === 2)
    ) {
      const p1Given0 = (cm[0] as number[])[1];
      const p0Given1 = (cm[1] as number[])[0];
      entries.push({ fidelityType: { name: "READOUT_ERROR_0_TO_1" }, fidelity: p1Given0 });
      entries.push({ fidelityType: { name: "READOUT_ERROR_1_TO_0" }, fidelity: p0Given1 });
    }
  }

  for (const bench of (props.benchmarks as unknown[]) ?? []) {
    if (!isObj(bench) || !isObj(bench.fidelity)) continue;
    const fid = bench.fidelity;
    const ftype = fidelityType(bench.protocol, fid.metric);
    if (ftype === null) continue;
    entries.push(fidelityEntry(fid.value, ftype, fid.std_error));
  }

  return entries;
}

export function toBraketStandardized(doc: OqCalDocument): object {
  const d = doc as unknown as Obj;

  const oneQubit: Record<string, Obj> = {};
  if (isObj(d.qubits)) {
    for (const [ref, props] of Object.entries(d.qubits)) {
      if (!isObj(props)) continue;
      const idx = qubitIndex(ref);
      if (idx === null) continue;
      const entry: Obj = {};
      const t1 = coherence(props.t1);
      const t2 = coherence(props.t2_echo ?? props.t2);
      if (t1 !== null) entry.T1 = t1;
      if (t2 !== null) entry.T2 = t2;
      const fidelities = oneQubitFidelity(props);
      if (fidelities.length > 0) entry.oneQubitFidelity = fidelities;
      if (Object.keys(entry).length > 0) oneQubit[String(idx)] = entry;
    }
  }

  const twoQubit: Record<string, Obj> = {};
  for (const entry of (d.gates as unknown[]) ?? []) {
    if (!isObj(entry)) continue;
    const qubits = Array.isArray(entry.qubits) ? entry.qubits : [];
    if (qubits.length !== 2) continue;
    const idx = qubits.map(qubitIndex);
    if (idx.some((i) => i === null)) continue;
    const key = `${idx[0]}-${idx[1]}`;

    const fidelities: Obj[] = [];
    if (isObj(entry.fidelity)) {
      const fid = entry.fidelity;
      const ftype = fidelityType(fid.method, fid.metric);
      if (ftype !== null) fidelities.push(fidelityEntry(fid.value, ftype, fid.std_error));
    } else if (isObj(entry.error) && entry.error.metric === "average_gate_error") {
      const err = entry.error;
      const ftype = fidelityType(err.method, null);
      if (ftype !== null) fidelities.push(fidelityEntry(1.0 - (err.value as number), ftype, null));
    }
    for (const bench of (entry.benchmarks as unknown[]) ?? []) {
      if (!isObj(bench) || !isObj(bench.fidelity)) continue;
      const fid = bench.fidelity;
      const ftype = fidelityType(bench.protocol, fid.metric);
      if (ftype === null) continue;
      fidelities.push(fidelityEntry(fid.value, ftype, fid.std_error));
    }

    if (fidelities.length === 0) continue;
    if (!(key in twoQubit)) twoQubit[key] = {};
    twoQubit[key]!.twoQubitGateFidelity = fidelities.map((f) => ({
      gateName: String(entry.name).toUpperCase(),
      ...f,
    }));
  }

  const result: Obj = {
    braketSchemaHeader: { name: SCHEMA_NAME, version: SCHEMA_VERSION },
  };
  if (Object.keys(oneQubit).length > 0) result.oneQubitProperties = oneQubit;
  if (Object.keys(twoQubit).length > 0) result.twoQubitProperties = twoQubit;
  return result;
}

function sourceIndex(doc: Obj, ref: string): number | null {
  const device = isObj(doc.device) ? doc.device : {};
  const labels = isObj(device.qubit_labels) ? device.qubit_labels : {};
  const label = labels[ref];
  if (typeof label === "string" && /^[0-9]+$/.test(label)) return parseInt(label, 10);
  return qubitIndex(ref);
}

function remapIndex(doc: Obj, index: string): string {
  const mapped = sourceIndex(doc, `$${index}`);
  return mapped === null ? index : String(mapped);
}

export function toBraketRigetti(doc: OqCalDocument): object {
  const d = doc as unknown as Obj;
  const device = isObj(d.device) ? d.device : {};
  const paradigm: Obj = {
    braketSchemaHeader: { name: PARADIGM_SCHEMA, version: "1" },
  };
  if (typeof device.num_qubits === "number") paradigm.qubitCount = device.num_qubits;

  const graph: Record<string, string[]> = {};
  if (Array.isArray(device.coupling_map)) {
    for (const pair of device.coupling_map) {
      if (!Array.isArray(pair) || pair.length !== 2) continue;
      const src = sourceIndex(d, String(pair[0]));
      const dst = sourceIndex(d, String(pair[1]));
      if (src === null || dst === null || src === dst) continue;
      const key = String(src);
      if (!(key in graph)) graph[key] = [];
      if (!graph[key]!.includes(String(dst))) graph[key]!.push(String(dst));
    }
  }
  for (const dests of Object.values(graph)) dests.sort((a, b) => parseInt(a, 10) - parseInt(b, 10));
  if (Object.keys(graph).length > 0) {
    paradigm.connectivity = { fullyConnected: false, connectivityGraph: graph };
  }

  const standardized = toBraketStandardized(doc) as Obj;
  const one = isObj(standardized.oneQubitProperties) ? standardized.oneQubitProperties : null;
  const two = isObj(standardized.twoQubitProperties) ? standardized.twoQubitProperties : null;
  let nested: Obj | null = null;
  if (one || two) {
    nested = { braketSchemaHeader: standardized.braketSchemaHeader };
    if (one) {
      const remapped: Obj = {};
      for (const [key, value] of Object.entries(one)) remapped[remapIndex(d, key)] = value;
      nested.oneQubitProperties = remapped;
    }
    if (two) {
      const remapped: Obj = {};
      for (const [key, value] of Object.entries(two)) {
        remapped[key.split("-").map((part) => remapIndex(d, part)).join("-")] = value;
      }
      nested.twoQubitProperties = remapped;
    }
  }

  const frames: Obj = {};
  if (Array.isArray(d.defcals)) {
    for (const defcal of d.defcals) {
      if (!isObj(defcal) || !isObj(defcal.params)) continue;
      const frequency = defcal.params.frequency_hz;
      if (typeof frequency !== "number") continue;
      const qubits = Array.isArray(defcal.qubits) ? defcal.qubits.map(String) : [];
      const indices: number[] = [];
      let ok = qubits.length > 0;
      for (const ref of qubits) {
        const idx = sourceIndex(d, ref);
        if (idx === null) {
          ok = false;
          break;
        }
        indices.push(idx);
      }
      if (!ok) continue;
      const frameId = `${String(defcal.gate)}_q${indices.join("_")}`;
      frames[frameId] = {
        frameId,
        frequency,
        associatedGate: defcal.gate,
        qubitMappings: indices,
      };
    }
  }

  const result: Obj = {
    braketSchemaHeader: { name: RIGETTI_SCHEMA, version: "2" },
    paradigm,
  };
  const snapshot = isObj(d.snapshot) ? d.snapshot : {};
  if (typeof snapshot.captured_at === "string" && snapshot.captured_at) {
    result.service = { updatedAt: snapshot.captured_at };
  }
  if (nested !== null) result.standardized = nested;
  if (Object.keys(frames).length > 0) result.pulse = { frames };
  return result;
}

export function toBraket(doc: OqCalDocument): object {
  const snapshot = (doc as unknown as Obj).snapshot;
  const schema = isObj(snapshot) && typeof snapshot.source_schema === "string" ? snapshot.source_schema : "";
  if (schema.includes("rigetti_device_capabilities")) return toBraketRigetti(doc);
  return toBraketStandardized(doc);
}
