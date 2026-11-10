// Importer for a Qiskit BackendProperties.to_dict() payload.
// Behavior-identical port of python/src/oq_cal/importers/ibm.py.
// Does not import Qiskit. gate_error stays an error. readout_error stays an
// assignment error. prob_meas* becomes a row-stochastic confusion matrix.

import type { OqCalDocument } from "../types.js";

export class IBMPropertiesError extends Error {}

const TIME: Record<string, number> = {
  "": 1,
  s: 1,
  sec: 1,
  ms: 1e-3,
  us: 1e-6,
  "µs": 1e-6,
  ns: 1e-9,
  ps: 1e-12,
};
const FREQ: Record<string, number> = { hz: 1, khz: 1e3, mhz: 1e6, ghz: 1e9 };
const GATE_NAME: Record<string, string> = {
  cnot: "cx",
  cx: "cx",
  cz: "cz",
  ecr: "ecr",
  swap: "swap",
  ccx: "ccx",
  x: "x",
  sx: "sx",
  rx: "rx",
  ry: "ry",
  rz: "rz",
  id: "id",
  h: "h",
  s: "s",
  sdg: "sdg",
  t: "t",
  tdg: "tdg",
  reset: "reset",
};

type Obj = Record<string, unknown>;

function isObj(v: unknown): v is Obj {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

function rfc3339(value: unknown): string | undefined {
  if (typeof value !== "string" || value.length === 0) return undefined;
  if (value.length >= 11 && value[10] === " ") return `${value.slice(0, 10)}T${value.slice(11)}`;
  return value;
}

function asFloat(value: unknown): number | null {
  return typeof value === "number" ? value : null;
}

function asIndex(value: unknown): number | null {
  if (typeof value === "number" && Number.isInteger(value)) return value;
  if (typeof value === "string" && /^[0-9]+$/.test(value)) return parseInt(value, 10);
  return null;
}

function nduv(entries: unknown): Map<string, Obj> {
  const found = new Map<string, Obj>();
  if (!Array.isArray(entries)) return found;
  for (const entry of entries) {
    if (isObj(entry) && typeof entry.name === "string") found.set(entry.name, entry);
  }
  return found;
}

function scale(entry: Obj, table: Record<string, number>): number | null {
  const value = asFloat(entry.value);
  if (value === null) return null;
  const unit = String(entry.unit ?? "")
    .trim()
    .toLowerCase()
    .replaceAll("μ", "µ");
  const factor = table[unit];
  return factor === undefined ? value : value * factor;
}

function timeDatum(entry: Obj | undefined): Obj | undefined {
  if (!entry) return undefined;
  const value = scale(entry, TIME);
  if (value === null) return undefined;
  const d: Obj = { value, unit: "s" };
  const stamp = rfc3339(entry.date);
  if (stamp) d.updated_at = stamp;
  return d;
}

function freqDatum(entry: Obj | undefined): Obj | undefined {
  if (!entry) return undefined;
  const value = scale(entry, FREQ);
  if (value === null) return undefined;
  const d: Obj = { value, unit: "Hz" };
  const stamp = rfc3339(entry.date);
  if (stamp) d.updated_at = stamp;
  return d;
}

function dimensionless(entry: Obj | undefined, extra: Obj = {}): Obj | undefined {
  if (!entry) return undefined;
  const value = asFloat(entry.value);
  if (value === null) return undefined;
  const d: Obj = { value, unit: "dimensionless", ...extra };
  const stamp = rfc3339(entry.date);
  if (stamp) d.updated_at = stamp;
  return d;
}

function buildQubit(entries: unknown): { props: Obj | null; keep: boolean } {
  if (!Array.isArray(entries)) return { props: null, keep: false };
  const fields = nduv(entries);
  const qp: Obj = {};
  const t1 = timeDatum(fields.get("T1"));
  const t2 = timeDatum(fields.get("T2"));
  const frequency = freqDatum(fields.get("frequency"));
  const anharmonicity = freqDatum(fields.get("anharmonicity"));
  if (t1) qp.t1 = t1;
  if (t2) qp.t2 = t2;
  if (frequency) qp.frequency_01 = frequency;
  if (anharmonicity) qp.anharmonicity = anharmonicity;

  const readout: Obj = {};
  const duration = timeDatum(fields.get("readout_length"));
  if (duration) readout.duration = duration;
  const p10 = asFloat(fields.get("prob_meas1_prep0")?.value);
  const p01 = asFloat(fields.get("prob_meas0_prep1")?.value);
  if (p10 !== null || p01 !== null) {
    const a = p10 ?? 0;
    const b = p01 ?? 0;
    readout.confusion_matrix = [
      [1 - a, a],
      [b, 1 - b],
    ];
  }
  if (Object.keys(readout).length > 0) qp.readout = readout;

  const assignment = dimensionless(fields.get("readout_error"), { metric: "assignment_error" });
  if (assignment) qp.benchmarks = [{ protocol: "readout", error: assignment }];

  return { props: Object.keys(qp).length > 0 ? qp : null, keep: true };
}

function buildGate(raw: Obj): Obj | null {
  const name = raw.gate;
  const qubits = raw.qubits;
  if (typeof name !== "string" || !Array.isArray(qubits) || qubits.length === 0) return null;
  if (name.toLowerCase() === "measure") return null;
  const refs: string[] = [];
  for (const qubit of qubits) {
    const idx = asIndex(qubit);
    if (idx === null) return null;
    refs.push(`$${idx}`);
  }
  const params = nduv(raw.parameters);
  const error = dimensionless(params.get("gate_error"), { metric: "average_gate_error" });
  const duration = timeDatum(params.get("gate_length"));
  if (!error && !duration) return null;
  const gate: Obj = { name: GATE_NAME[name.toLowerCase()] ?? name.toLowerCase(), qubits: refs };
  if (error) gate.error = error;
  if (duration) gate.duration = duration;
  return gate;
}

export interface IbmOptions {
  numQubits?: number;
  deviceId?: string;
  vendor?: string;
  model?: string;
  capturedAt?: string;
  snapshotId?: string;
}

export function fromIbmProperties(payload: object, opts: IbmOptions = {}): OqCalDocument {
  const p = payload as Obj;
  if (!Array.isArray(p.qubits)) {
    throw new IBMPropertiesError(
      "IBM properties payload needs a 'qubits' list (Qiskit BackendProperties.to_dict())",
    );
  }

  const qubits: Obj = {};
  p.qubits.forEach((entries, index) => {
    const built = buildQubit(entries);
    if (built.keep && built.props) qubits[`$${index}`] = built.props;
  });

  const gates: Obj[] = [];
  const rawGates = Array.isArray(p.gates) ? p.gates : [];
  for (const raw of rawGates) {
    if (!isObj(raw)) continue;
    const gate = buildGate(raw);
    if (gate) gates.push(gate);
  }

  const pairs = new Map<string, [number, number]>();
  for (const gate of gates) {
    const refs = gate.qubits as string[];
    if (refs.length === 2) {
      const i = parseInt(refs[0]!.slice(1), 10);
      const j = parseInt(refs[1]!.slice(1), 10);
      pairs.set(`${i},${j}`, [i, j]);
    }
  }

  let roster = p.qubits.length;
  if (opts.numQubits !== undefined) roster = Math.max(roster, opts.numQubits);
  const backendName = p.backend_name;
  const device: Obj = {
    id: typeof backendName === "string" && backendName ? backendName : "ibm-device",
    num_qubits: roster,
  };
  if (pairs.size > 0) {
    device.coupling_map = [...pairs.values()]
      .sort((a, b) => a[0] - b[0] || a[1] - b[1])
      .map(([i, j]) => [`$${i}`, `$${j}`]);
  }
  if (opts.deviceId !== undefined) device.id = opts.deviceId;
  if (opts.vendor !== undefined) device.vendor = opts.vendor;
  if (opts.model !== undefined) device.model = opts.model;

  const snapshot: Obj = {
    source: "ibm-properties",
    source_schema: "qiskit.providers.models.BackendProperties",
  };
  const captured = rfc3339(p.last_update_date);
  if (captured) snapshot.captured_at = captured;
  if (opts.capturedAt !== undefined) snapshot.captured_at = opts.capturedAt;
  if (opts.snapshotId !== undefined) snapshot.id = opts.snapshotId;

  const doc: Obj = {
    "oq-cal": { name: "oq-cal.device_calibration", version: "0.1" },
    device,
    snapshot,
    extensions: { ibm: payload },
  };
  if (Object.keys(qubits).length > 0) doc.qubits = qubits;
  if (gates.length > 0) doc.gates = gates;
  return doc as unknown as OqCalDocument;
}
