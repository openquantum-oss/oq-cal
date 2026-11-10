// Importer for a QUAM (Quantum Abstraction Machine) state.json tree.
// Behavior-identical port of python/src/oq_cal/importers/quam.py. Duck-typed and
// tolerant: never throws on a thin tree. A document with only the required sections is valid.

import type { Datum, OqCalDocument } from "../types.js";

type Obj = Record<string, unknown>;

const PULSE_GATE: Record<string, string> = {
  x180: "x",
  x90: "sx",
  y180: "y",
  y90: "sy",
  measure: "measure",
  readout: "measure",
};

const NS_PER_SAMPLE = 1e-9; // default QUA 1 GS/s: length in samples == nanoseconds
const RATE_KEYS = [
  "sampling_rate",
  "sample_rate",
  "clock",
  "sampling_rate_hz",
  "sample_rate_hz",
];

function isObj(v: unknown): v is Obj {
  return typeof v === "object" && v !== null && !Array.isArray(v);
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

// Resolve an absolute "#/..." reference against root; tolerate failure.
function resolve(root: Obj, value: unknown): unknown {
  if (!(typeof value === "string" && value.startsWith("#/"))) return value;
  const path = value.slice(2).split("/");
  let node: unknown = root;
  for (const part of path) {
    if (isObj(node) && part in node) {
      node = node[part];
    } else {
      return null;
    }
  }
  return node;
}

function getCi(d: Obj, ...names: string[]): unknown {
  const lower = new Map<string, unknown>();
  for (const [k, v] of Object.entries(d)) lower.set(k.toLowerCase(), v);
  for (const name of names) {
    if (lower.has(name.toLowerCase())) return lower.get(name.toLowerCase());
  }
  return undefined;
}

function numDatum(raw: unknown, unit: string): Datum | undefined {
  if (raw === null || raw === undefined || isObj(raw) || Array.isArray(raw) || typeof raw === "string") {
    return undefined;
  }
  const value = Number(raw);
  if (!Number.isFinite(value) && typeof raw !== "number") return undefined;
  return { value, unit: unit as Datum["unit"] };
}

function isQubitLike(value: unknown): boolean {
  if (!isObj(value)) return false;
  const cls = String(value.__class__ ?? "").toLowerCase();
  return cls.includes("transmon") || cls.includes("qubit");
}

function extractQubit(comp: Obj): Obj {
  const qp: Obj = {};
  const set = (k: string, d: Datum | undefined): void => {
    if (d !== undefined) qp[k] = d;
  };
  set("t1", numDatum(getCi(comp, "T1", "t1"), "s"));
  set("t2", numDatum(getCi(comp, "T2", "t2", "T2ramsey", "t2_ramsey"), "s"));
  set("t2_echo", numDatum(getCi(comp, "T2echo", "t2_echo", "T2_echo"), "s"));
  set("frequency_01", numDatum(getCi(comp, "f_01", "frequency", "resonance_frequency", "freq_01"), "Hz"));
  set("anharmonicity", numDatum(getCi(comp, "anharmonicity", "anharm"), "Hz"));
  return qp;
}

function secondsPerSample(...nodes: unknown[]): number {
  for (const node of nodes) {
    if (!isObj(node)) continue;
    const raw = getCi(node, ...RATE_KEYS);
    if (typeof raw === "number" && raw > 0) return 1 / raw;
  }
  return NS_PER_SAMPLE;
}

function pulseParams(pulse: Obj, secondsPerSampleValue: number): Obj {
  const p: Obj = {};
  const amp = getCi(pulse, "amplitude", "amp");
  if (typeof amp === "number") p.amp = amp;
  const length = getCi(pulse, "length", "duration");
  if (typeof length === "number") p.duration_s = length * secondsPerSampleValue;
  const alpha = getCi(pulse, "alpha", "motzoi", "drag");
  if (typeof alpha === "number") p.motzoi = alpha;
  return p;
}

function extractDefcals(comp: Obj, ref: string, root: Obj): Obj[] {
  const defcals: Obj[] = [];
  for (const chanKey of ["xy", "resonator", "z", "drive"]) {
    const chan = resolve(root, comp[chanKey]);
    if (!isObj(chan)) continue;
    const ops = chan.operations;
    if (!isObj(ops)) continue;
    for (const [opName, rawPulse] of Object.entries(ops)) {
      const pulse = resolve(root, rawPulse);
      if (!isObj(pulse)) continue;
      const gate = PULSE_GATE[opName.toLowerCase()];
      if (gate === undefined) continue;
      const params = pulseParams(pulse, secondsPerSample(pulse, chan, comp, root));
      const dc: Obj = { gate, qubits: [ref] };
      if (Object.keys(params).length > 0) dc.params = params;
      defcals.push(dc);
    }
  }
  return defcals;
}

export interface QuamOptions {
  // Convert-time identity / provenance overrides (win over source-derived).
  deviceId?: string;
  vendor?: string;
  model?: string;
  capturedAt?: string;
  snapshotId?: string;
}

export function fromQuamState(
  payload: object,
  opts: QuamOptions = {},
): OqCalDocument {
  const root = payload as Obj;

  // Locate the qubit container.
  let qubitContainer: Obj = {};
  if (isObj(root.qubits)) {
    qubitContainer = root.qubits;
  } else {
    for (const value of Object.values(root)) {
      if (isObj(value) && Object.entries(value).some(([, v]) => isQubitLike(v))) {
        qubitContainer = {};
        for (const [k, v] of Object.entries(value)) {
          if (isQubitLike(v)) qubitContainer[k] = v;
        }
        break;
      }
    }
  }

  // Deterministic ordering, honoring a numeric "id".
  const items: [string, Obj][] = Object.entries(qubitContainer)
    .filter(([, v]) => isQubitLike(v))
    .map(([k, v]) => [k, v as Obj]);

  const sortKey = (item: [string, Obj]): [number, string] => {
    const cid = item[1].id;
    return [typeof cid === "number" && Number.isInteger(cid) ? cid : 1 << 30, item[0]];
  };
  items.sort((a, b) => {
    const [ak, as] = sortKey(a);
    const [bk, bs] = sortKey(b);
    if (ak !== bk) return ak - bk;
    return as < bs ? -1 : as > bs ? 1 : 0;
  });

  const nameToRef: Record<string, string> = {};
  const refToLabel: Record<string, string> = {};
  const qubits: Record<string, Obj> = {};
  const defcals: Obj[] = [];
  // Keep identity map from component object -> name for pair resolution.
  const nodeToName = new Map<Obj, string>();

  items.forEach(([name, comp], i) => {
    const ref = `$${i}`;
    nameToRef[name] = ref;
    refToLabel[ref] = name;
    nodeToName.set(comp, name);

    const qp = extractQubit(comp);
    if (Object.keys(qp).length > 0) qubits[ref] = qp;
    defcals.push(...extractDefcals(comp, ref, root));
  });

  // qubit_pairs -> two-qubit defcals.
  const pairs = root.qubit_pairs;
  if (isObj(pairs)) {
    for (const pair of Object.values(pairs)) {
      if (!isObj(pair)) continue;
      const ctrl = resolve(root, pair.qubit_control);
      const tgt = resolve(root, pair.qubit_target);
      const refs: string[] = [];
      for (const node of [ctrl, tgt]) {
        if (isObj(node)) {
          const nm = nodeToName.get(node);
          if (nm !== undefined) refs.push(nameToRef[nm]!);
        }
      }
      const coupler = resolve(root, pair.coupler);
      if (isObj(coupler) && refs.length === 2) {
        const ops = coupler.operations;
        if (isObj(ops)) {
          for (const [opName, rawPulse] of Object.entries(ops)) {
            const pulse = resolve(root, rawPulse);
            if (!isObj(pulse)) continue;
            const gate = PULSE_GATE[opName.toLowerCase()] ?? opName.toLowerCase();
            const params = pulseParams(pulse, secondsPerSample(pulse, coupler, root));
            const dc: Obj = { gate, qubits: refs };
            if (Object.keys(params).length > 0) dc.params = params;
            defcals.push(dc);
          }
        }
      }
    }
  }

  const numQubits = items.length;

  // coupling_map from the two-qubit evidence actually extracted (2q defcals).
  const pairEvidence = new Set<string>();
  for (const dc of defcals) {
    const dcq = dc.qubits as string[];
    if (dcq.length === 2) {
      pairEvidence.add(`${parseInt(dcq[0]!.slice(1), 10)},${parseInt(dcq[1]!.slice(1), 10)}`);
    }
  }

  // device identity: source name field, else default. A deviceId override is
  // applied below (wins over the source-derived value).
  let devId: unknown = getCi(root, "name", "id") ?? "quam-device";
  if (typeof devId !== "string") devId = "quam-device";
  if (opts.deviceId !== undefined) devId = opts.deviceId;

  const device: Obj = { id: devId, num_qubits: numQubits };
  if (opts.vendor !== undefined) device.vendor = opts.vendor;
  if (opts.model !== undefined) device.model = opts.model;
  if (Object.keys(refToLabel).length > 0) device.qubit_labels = refToLabel;
  if (pairEvidence.size > 0) device.coupling_map = couplingMap(pairEvidence);
  const deviceOrdered: Obj = {};
  for (const key of ["id", "vendor", "model", "num_qubits", "qubit_labels", "coupling_map"]) {
    if (key in device) deviceOrdered[key] = device[key];
  }

  const snapshot: Obj = { source: "quam-state", source_schema: "quam-state.json" };
  if (opts.capturedAt !== undefined) snapshot.captured_at = opts.capturedAt;
  if (opts.snapshotId !== undefined) snapshot.id = opts.snapshotId;

  const doc: Obj = {
    "oq-cal": { name: "oq-cal.device_calibration", version: "0.1" },
    device: deviceOrdered,
    snapshot,
  };
  if (Object.keys(qubits).length > 0) doc.qubits = qubits;
  if (defcals.length > 0) doc.defcals = defcals;
  doc.extensions = { quam: payload };

  return doc as unknown as OqCalDocument;
}
