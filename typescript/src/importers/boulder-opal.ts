// Importer for a Boulder Opal calibration snapshot (Q-CTRL product).
// Behavior-identical port of python/src/oq_cal/importers/boulder_opal.py.
//
// $n comes from the full roster (qubit_cal order, else the sorted union of
// transmon labels and enabled_qubits). qubit_cal wins for coherence and
// frequency; a null field is omitted. Confusion matrices are transposed only
// when the columns sum to ~1 more tightly than the rows. On x/sx, a frequency
// that matches the measure defcal is the readout tone and is replaced with the
// drive; the OpenQASM program string is copied and not parsed.

import type { Datum, OqCalDocument } from "../types.js";

type Obj = Record<string, unknown>;

const STATUS = new Set(["good", "approximate", "stale", "bad", "unmeasured"]);
const CM_TOL = 0.02;

const GATE_NAME: Record<string, string> = {
  x: "x",
  y: "y",
  z: "z",
  h: "h",
  s: "s",
  sx: "sx",
  sy: "sy",
  rz: "rz",
  cz: "cz",
  cx: "cx",
  swap: "swap",
  measure: "measure",
  x90: "sx",
  cphase: "cz",
  cnot: "cx",
};

// qubit_cal field, component field, oq-cal field, unit, whether it is a time.
const QUBIT_FIELDS: [string, string, string, string, boolean][] = [
  ["frequency", "freq_01", "frequency_01", "Hz", false],
  ["anharmonicity", "anharm", "anharmonicity", "Hz", false],
  ["t1", "t1", "t1", "s", true],
  ["t2", "t2", "t2", "s", true],
  ["t2_echo", "t2_echo", "t2_echo", "s", true],
];

function isObj(v: unknown): v is Obj {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

function isNumber(v: unknown): v is number {
  return typeof v === "number" && Number.isFinite(v);
}

function unitToSeconds(value: number, unit: string | undefined): number {
  const u = (unit ?? "").toLowerCase();
  if (u === "ns") return value * 1e-9;
  if (u === "us") return value * 1e-6;
  if (u === "ms") return value * 1e-3;
  return value;
}

function rfc3339(raw: string): string {
  if (raw.length >= 11 && raw[10] === " ") return raw.slice(0, 10) + "T" + raw.slice(11);
  return raw;
}

function errorNumber(raw: unknown, factor: number): number | undefined {
  // A bare number shares the unscaled source unit (factor = SI / source).
  // A duration object carries its own unit and is converted directly.
  if (raw === null || raw === undefined || typeof raw === "boolean") return undefined;
  if (isNumber(raw)) return raw * factor;
  if (!isObj(raw)) return undefined;
  const val = raw.value;
  if (!isNumber(val)) return undefined;
  const unit = raw.unit;
  if (typeof unit === "string" || raw.dtype === "duration") {
    return unitToSeconds(val, typeof unit === "string" ? unit : undefined);
  }
  return val * factor;
}

function datum(raw: unknown, unit: string, seconds = false): Datum | undefined {
  if (raw === null || raw === undefined) return undefined;

  let value: number;
  let factor: number;
  let status: unknown;
  let updated: unknown;

  if (!isObj(raw)) {
    if (!isNumber(raw)) return undefined;
    value = seconds ? unitToSeconds(raw, "s") : raw;
    return { value, unit: unit as Datum["unit"] };
  }

  const inner = raw.value;
  if (isObj(inner)) {
    if (!isNumber(inner.value)) return undefined;
    value = unitToSeconds(inner.value, typeof inner.unit === "string" ? inner.unit : undefined);
    factor = inner.value ? value / inner.value : 1.0;
  } else if (isNumber(inner)) {
    value = seconds ? unitToSeconds(inner, "s") : inner;
    factor = 1.0;
  } else {
    return undefined;
  }

  status = raw.calibration_status;
  if (status === "unmeasured" && value === 0) return undefined;

  const d: Obj = { value, unit };
  // dict.get: a present null does not fall through to the alternate key.
  const em = errorNumber("err_minus" in raw ? raw.err_minus : raw.error_minus, factor);
  const ep = errorNumber("err_plus" in raw ? raw.err_plus : raw.error_plus, factor);
  if (em !== undefined && ep !== undefined) {
    d.err_minus = em;
    d.err_plus = ep;
  }
  if (typeof status === "string" && STATUS.has(status)) d.status = status;
  updated = raw.updated_at ?? raw.last_calibrated;
  if (typeof updated === "string" && updated) d.updated_at = rfc3339(updated);
  return d as unknown as Datum;
}

function fromQubitCal(field: unknown, compField: unknown, unit: string): Datum | undefined {
  // qubit_cal values are already SI. A null field is omitted, not filled from
  // the component tree. Status comes from the matching component measurement.
  if (!isObj(field) || !isNumber(field.value)) return undefined;
  const d: Obj = { value: field.value, unit };
  const em = errorNumber(field.error_minus, 1.0);
  const ep = errorNumber(field.error_plus, 1.0);
  if (em !== undefined && ep !== undefined) {
    d.err_minus = em;
    d.err_plus = ep;
  }
  if (isObj(compField)) {
    const status = compField.calibration_status;
    if (typeof status === "string" && STATUS.has(status) && status !== "unmeasured") {
      d.status = status;
    }
  }
  let updated: unknown = field.last_calibrated;
  if (typeof updated !== "string" || !updated) {
    updated = isObj(compField) ? compField.updated_at : undefined;
  }
  if (typeof updated === "string" && updated) d.updated_at = rfc3339(updated);
  return d as unknown as Datum;
}

function maxAbsDev(sums: number[]): number {
  let max = 0;
  for (const s of sums) max = Math.max(max, Math.abs(s - 1));
  return max;
}

function orientConfusion(cm: unknown): unknown {
  if (!Array.isArray(cm) || cm.length === 0 || !Array.isArray(cm[0])) return cm;
  const width = cm[0].length;
  if (width === 0 || cm.some((row) => !Array.isArray(row) || row.length !== width)) return cm;
  const rows = cm as number[][];
  const rowSums = rows.map((row) => row.reduce((a, b) => a + Number(b), 0));
  const colSums = rows[0]!.map((_, j) => rows.reduce((a, row) => a + Number(row[j]), 0));
  const rowDev = maxAbsDev(rowSums);
  const colDev = maxAbsDev(colSums);
  if (colDev <= CM_TOL && colDev < rowDev) {
    return rows[0]!.map((_, j) => rows.map((row) => row[j]));
  }
  return cm;
}

function roster(payload: Obj): [string[], Record<string, Obj> | undefined] {
  const qc = payload.qubit_cal;
  if (Array.isArray(qc)) {
    const labels: string[] = [];
    const byLabel: Record<string, Obj> = {};
    for (const entry of qc) {
      if (isObj(entry) && typeof entry.qubit === "string") {
        labels.push(entry.qubit);
        byLabel[entry.qubit] = entry;
      }
    }
    if (labels.length > 0) return [labels, byLabel];
  }

  const labels = new Set<string>();
  const components = isObj(payload.components) ? payload.components : {};
  for (const [key, comp] of Object.entries(components)) {
    if (isObj(comp) && comp.dtype === "transmon") labels.add(key);
  }
  if (Array.isArray(payload.enabled_qubits)) {
    for (const lab of payload.enabled_qubits) {
      if (typeof lab === "string") labels.add(lab);
    }
  }
  return [[...labels].sort(), undefined];
}

function labelMaps(labels: string[]): [Record<string, string>, Record<string, string>] {
  const labelToRef: Record<string, string> = {};
  const refToLabel: Record<string, string> = {};
  labels.forEach((label, i) => {
    const ref = `$${i}`;
    labelToRef[label] = ref;
    refToLabel[ref] = label;
  });
  return [labelToRef, refToLabel];
}

function operationalLabels(
  payload: Obj,
  labels: string[],
  calIndex: Record<string, Obj> | undefined,
): string[] {
  if (calIndex !== undefined) {
    return labels.filter((label) => calIndex[label]?.operational === true);
  }
  const enabled = new Set<string>();
  if (Array.isArray(payload.enabled_qubits)) {
    for (const lab of payload.enabled_qubits) {
      if (typeof lab === "string") enabled.add(lab);
    }
  }
  return labels.filter((label) => enabled.has(label));
}

function buildQubit(
  comp: Obj,
  classifier: Obj | undefined,
  calEntry: Obj | undefined | null,
): Obj {
  const qp: Obj = {};
  for (const [calKey, compKey, attr, unit, seconds] of QUBIT_FIELDS) {
    const compField = comp[compKey];
    // An explicit qubit_cal entry (even with null fields) does not fall back
    // to the component tree. A missing entry does.
    const d =
      calEntry != null
        ? fromQubitCal(calEntry[calKey], compField, unit)
        : datum(compField, unit, seconds);
    if (d !== undefined) qp[attr] = d;
  }
  const ordered: Obj = {};
  for (const key of ["t1", "t2", "t2_echo", "frequency_01", "anharmonicity"]) {
    if (key in qp) ordered[key] = qp[key];
  }

  if (classifier && isObj(classifier)) {
    const ro: Obj = {};
    const cm = classifier.confusion_matrix;
    if (Array.isArray(cm) && cm.length > 0) {
      const oriented = orientConfusion(cm) as number[][];
      ro.confusion_matrix = oriented;
      const diag = oriented.map((row, i) => Number(row[i]));
      const fidelity = diag.reduce((a, b) => a + b, 0) / diag.length;
      ro.fidelity = {
        value: fidelity,
        unit: "dimensionless",
        method: "confusion_matrix_diagonal",
        metric: "readout_fidelity",
      };
    }
    ro.classifier = {
      type: "linear_iq",
      projection: classifier.projection,
      threshold: classifier.threshold,
      status: classifier.status,
    };
    const roOrdered: Obj = {};
    for (const key of ["fidelity", "duration", "confusion_matrix", "classifier"]) {
      if (key in ro) roOrdered[key] = ro[key];
    }
    ordered.readout = roOrdered;
  }

  return ordered;
}

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

function refIndex(ref: string): number {
  return parseInt(ref.slice(1), 10);
}

function driveHz(
  label: string,
  components: Obj,
  calIndex: Record<string, Obj> | undefined,
): number | undefined {
  if (calIndex !== undefined) {
    const freq = calIndex[label]?.frequency;
    if (isObj(freq) && isNumber(freq.value)) return freq.value;
  }
  const d = datum((isObj(components[label]) ? components[label] : {})?.freq_01, "Hz");
  return d?.value;
}

function sameHz(a: number, b: number): boolean {
  const relTol = 1e-9;
  const absTol = 1.0;
  return Math.abs(a - b) <= Math.max(relTol * Math.max(Math.abs(a), Math.abs(b)), absTol);
}

function buildDefcal(
  key: string,
  params: Obj,
  labelToRef: Record<string, string>,
  drive: number | undefined,
  measure: number | undefined,
): Obj | null {
  if (!key.includes(":")) return null;
  const idx = key.indexOf(":");
  const gateRaw = key.slice(0, idx);
  const addr = key.slice(idx + 1);
  const gate = GATE_NAME[gateRaw.toLowerCase()] ?? gateRaw.toLowerCase();
  const labels = addr.split("_");
  const qubits: string[] = [];
  for (const lab of labels) {
    const ref = labelToRef[lab];
    if (ref === undefined) return null;
    qubits.push(ref);
  }

  const p: Obj = {};
  if ("duration" in params) p.duration_s = Number(params.duration);
  if ("amp" in params) p.amp = Number(params.amp);
  if ("motzoi" in params) p.motzoi = Number(params.motzoi);
  if ("frequency" in params) {
    let frequency = Number(params.frequency);
    // x/sx store the readout tone when it matches the measure defcal.
    // The drive is freq_01 / qubit_cal.frequency. The program is not parsed.
    if (
      (gate === "x" || gate === "sx") &&
      drive !== undefined &&
      measure !== undefined &&
      sameHz(frequency, measure)
    ) {
      frequency = drive;
    }
    p.frequency_hz = frequency;
  }
  if ("integration_time" in params) p.integration_time_s = Number(params.integration_time);
  for (const [k, v] of Object.entries(params)) {
    if (!["duration", "amp", "motzoi", "frequency", "integration_time"].includes(k)) {
      p[k] = v;
    }
  }

  const defcal: Obj = { gate, qubits };
  if (Object.keys(p).length > 0) defcal.params = p;
  return defcal;
}

export interface BoulderOpalOptions {
  // Convert-time identity / provenance overrides (win over source-derived).
  deviceId?: string;
  vendor?: string;
  model?: string;
  capturedAt?: string;
  snapshotId?: string;
}

export function fromBoulderOpal(
  payload: object,
  opts: BoulderOpalOptions = {},
): OqCalDocument {
  const p = payload as Obj;
  const [labels, calIndex] = roster(p);
  const [labelToRef, refToLabel] = labelMaps(labels);
  const operational = operationalLabels(p, labels, calIndex);

  const components = isObj(p.components) ? p.components : {};
  const classifiers = isObj(p.classifiers) ? p.classifiers : {};

  const qubits: Record<string, Obj> = {};
  for (const label of labels) {
    const ref = labelToRef[label]!;
    const comp = isObj(components[label]) ? (components[label] as Obj) : {};
    const dtype = comp.dtype;
    if (dtype !== undefined && dtype !== null && dtype !== "transmon") continue;
    // A missing qubit_cal record falls back to the component. A present record
    // does not, even when its fields are null.
    const calEntry = calIndex === undefined ? undefined : calIndex[label];
    const qp = buildQubit(comp, classifiers[label] as Obj | undefined, calEntry);
    if (Object.keys(qp).length > 0) qubits[ref] = qp;
  }

  const defcals: Obj[] = [];
  const pairEvidence = new Set<string>();
  const defcalsSrc = isObj(p.defcals) ? p.defcals : {};
  for (const [key, params] of Object.entries(defcalsSrc)) {
    if (!isObj(params) || !key.includes(":")) continue;
    const addr = key.slice(key.indexOf(":") + 1);
    const labs = addr.split("_");
    let drive: number | undefined;
    let measure: number | undefined;
    if (labs.length === 1) {
      drive = driveHz(labs[0]!, components, calIndex);
      const measureSrc = defcalsSrc[`measure:${labs[0]}`];
      if (isObj(measureSrc) && isNumber(measureSrc.frequency)) measure = measureSrc.frequency;
    }
    const dc = buildDefcal(key, params, labelToRef, drive, measure);
    if (dc !== null) {
      defcals.push(dc);
      const dcq = dc.qubits as string[];
      if (dcq.length === 2) pairEvidence.add(`${refIndex(dcq[0]!)},${refIndex(dcq[1]!)}`);
    }
  }

  const gates: Obj[] = [];
  for (const ge of (p.gate_errors as unknown[]) ?? []) {
    if (!isObj(ge)) continue;
    const geLabels = Array.isArray(ge.qubits) ? (ge.qubits as string[]) : [];
    const refs: string[] = [];
    let ok = true;
    for (const lab of geLabels) {
      const ref = labelToRef[lab];
      if (ref === undefined) {
        ok = false;
        break;
      }
      refs.push(ref);
    }
    if (!ok || refs.length === 0) continue;
    const gateRaw = (ge.gate as string) ?? "";
    const name = GATE_NAME[gateRaw.toLowerCase()] ?? gateRaw.toLowerCase();
    const error: Obj = { value: Number(ge.value), unit: "dimensionless" };
    const calStatus = ge.calibration_status;
    if (typeof calStatus === "string" && STATUS.has(calStatus)) error.status = calStatus;
    if (ge.updated_at) error.updated_at = ge.updated_at;
    gates.push({ name, qubits: refs, error });
    if (refs.length === 2) pairEvidence.add(`${refIndex(refs[0]!)},${refIndex(refs[1]!)}`);
  }

  const sourceModel = typeof p.qpu_model === "string" && p.qpu_model ? p.qpu_model : undefined;
  const device: Obj = {
    id: opts.deviceId ?? sourceModel ?? "boulder-opal-device",
    num_qubits: labels.length,
  };
  if (opts.vendor !== undefined) device.vendor = opts.vendor;
  if (sourceModel !== undefined) device.model = sourceModel;
  if (opts.model !== undefined) device.model = opts.model;
  if (Object.keys(refToLabel).length > 0) {
    device.qubit_labels = refToLabel;
    device.enabled_qubits = operational.map((label) => labelToRef[label]!);
  }
  if (pairEvidence.size > 0) device.coupling_map = couplingMap(pairEvidence);
  const deviceOrdered: Obj = {};
  for (const key of ["id", "vendor", "model", "num_qubits", "qubit_labels", "enabled_qubits", "coupling_map"]) {
    if (key in device) deviceOrdered[key] = device[key];
  }

  const snapshot: Obj = { source: "boulder-opal", source_schema: "boulder-opal-snapshot" };
  if (typeof p.version === "string" && p.version) snapshot.captured_at = rfc3339(p.version);
  if (opts.capturedAt !== undefined) snapshot.captured_at = opts.capturedAt;
  if (opts.snapshotId !== undefined) snapshot.id = opts.snapshotId;
  const snapshotOrdered: Obj = {};
  for (const key of ["id", "captured_at", "source", "source_schema"]) {
    if (key in snapshot) snapshotOrdered[key] = snapshot[key];
  }

  const doc: Obj = {
    "oq-cal": { name: "oq-cal.device_calibration", version: "0.1" },
    device: deviceOrdered,
    snapshot: snapshotOrdered,
  };
  if (Object.keys(qubits).length > 0) doc.qubits = qubits;
  if (gates.length > 0) doc.gates = gates;
  if (defcals.length > 0) doc.defcals = defcals;
  doc.extensions = { boulder_opal: payload };

  return doc as unknown as OqCalDocument;
}
