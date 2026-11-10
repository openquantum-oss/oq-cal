// Calibration drift engine: compare two oq-cal documents datum-by-datum.
// Mirrors python/src/oq_cal/diff.py (thresholds, keying, classification).

import type { OqCalDocument } from "./types.js";

export const MAJOR_REL = 0.2;
export const MINOR_REL = 0.05;

export type Significance = "major" | "minor" | "noise";

export interface DiffEntry {
  path: string;
  a_value: number | null;
  b_value: number | null;
  abs_change: number | null;
  rel_change: number | null;
  significance: Significance;
  // Set only on a status-string change. Numeric fields stay null.
  a_status?: string | null;
  b_status?: string | null;
}

export interface DiffSummary {
  counts: Record<Significance, number>;
  total: number;
  worst_offenders: {
    path: string;
    a_value: number | null;
    b_value: number | null;
    rel_change: number | null;
    significance: Significance;
    a_status: string | null;
    b_status: string | null;
  }[];
}

export class OqCalDiff {
  entries: DiffEntry[];

  constructor(entries: DiffEntry[] = []) {
    this.entries = entries;
  }

  get counts(): Record<Significance, number> {
    const out: Record<Significance, number> = { major: 0, minor: 0, noise: 0 };
    for (const e of this.entries) out[e.significance] += 1;
    return out;
  }

  worstOffenders(n = 5): DiffEntry[] {
    const keyed = this.entries.map((e) => ({
      e,
      // Status entries are not numeric; rank them after value changes.
      rel:
        e.a_status != null || e.b_status != null
          ? 0
          : e.rel_change !== null
            ? Math.abs(e.rel_change)
            : Infinity,
    }));
    // Stable sort by magnitude of relative change, descending
    // (appeared/disappeared -> Infinity sort first).
    keyed.sort((x, y) => y.rel - x.rel);
    return keyed.slice(0, n).map((k) => k.e);
  }

  summary(): DiffSummary {
    return {
      counts: this.counts,
      total: this.entries.length,
      worst_offenders: this.worstOffenders().map((e) => ({
        path: e.path,
        a_value: e.a_value,
        b_value: e.b_value,
        rel_change: e.rel_change,
        significance: e.significance,
        a_status: e.a_status ?? null,
        b_status: e.b_status ?? null,
      })),
    };
  }
}

function classify(a: number | null, b: number | null): DiffEntry {
  const appeared = a === null && b !== null;
  const disappeared = a !== null && b === null;

  if (appeared || disappeared) {
    return {
      path: "",
      a_value: a,
      b_value: b,
      abs_change: null,
      rel_change: null,
      significance: "major",
    };
  }

  // Both present.
  const av = a as number;
  const bv = b as number;
  const absChange = bv - av;
  let relChange: number | null;
  let significance: Significance;
  if (av === 0) {
    relChange = null;
    significance = absChange !== 0 ? "major" : "noise";
  } else {
    relChange = absChange / av;
    const mag = Math.abs(relChange);
    if (mag > MAJOR_REL) significance = "major";
    else if (mag > MINOR_REL) significance = "minor";
    else significance = "noise";
  }
  return {
    path: "",
    a_value: av,
    b_value: bv,
    abs_change: absChange,
    rel_change: relChange,
    significance,
  };
}

function entry(path: string, a: number | null, b: number | null): DiffEntry | null {
  if (a === null && b === null) return null;
  const base = classify(a, b);
  return { ...base, path };
}

function isObject(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

function datumValue(datum: unknown): number | null {
  if (!isObject(datum)) return null;
  const v = datum.value;
  return typeof v === "number" ? v : null;
}

const LABELS = ["status", "method", "metric"] as const;

function datumLabel(datum: unknown, field: (typeof LABELS)[number]): string | null {
  if (!isObject(datum)) return null;
  const value = datum[field];
  return typeof value === "string" && value.length > 0 ? value : null;
}

function collectScalars(doc: OqCalDocument): Map<string, number> {
  const out = new Map<string, number>();
  const put = (path: string, value: number | null): void => {
    if (value !== null && value !== undefined) out.set(path, value);
  };
  const d = doc as unknown as Record<string, unknown>;

  // --- aggregates ---
  const agg = d.aggregates;
  if (isObject(agg)) {
    if (isObject(agg.qubits)) {
      put("aggregates.qubits.t1", datumValue(agg.qubits.t1));
      put("aggregates.qubits.t2", datumValue(agg.qubits.t2));
      put("aggregates.qubits.t2_echo", datumValue(agg.qubits.t2_echo));
    }
    if (isObject(agg.readout)) {
      put("aggregates.readout.fidelity", datumValue(agg.readout.fidelity));
      put("aggregates.readout.duration", datumValue(agg.readout.duration));
    }
    for (const gname of ["gates_1q", "gates_2q"] as const) {
      const g = agg[gname];
      if (isObject(g)) {
        put(`aggregates.${gname}.fidelity`, datumValue(g.fidelity));
        put(`aggregates.${gname}.error`, datumValue(g.error));
        put(`aggregates.${gname}.duration`, datumValue(g.duration));
      }
    }
    if (isObject(agg.ops)) {
      for (const [op, datum] of Object.entries(agg.ops)) {
        put(`aggregates.ops.${op}`, datumValue(datum));
      }
    }
  }

  // --- qubits ---
  if (isObject(d.qubits)) {
    for (const [ref, props] of Object.entries(d.qubits)) {
      if (!isObject(props)) continue;
      const base = `qubits.${ref}`;
      put(`${base}.t1`, datumValue(props.t1));
      put(`${base}.t2`, datumValue(props.t2));
      put(`${base}.t2_echo`, datumValue(props.t2_echo));
      put(`${base}.frequency_01`, datumValue(props.frequency_01));
      put(`${base}.anharmonicity`, datumValue(props.anharmonicity));
      if (isObject(props.readout)) {
        put(`${base}.readout.fidelity`, datumValue(props.readout.fidelity));
        put(`${base}.readout.duration`, datumValue(props.readout.duration));
        const cm = props.readout.confusion_matrix;
        if (Array.isArray(cm)) {
          cm.forEach((row, i) => {
            if (Array.isArray(row)) {
              row.forEach((v, j) => {
                if (typeof v === "number") {
                  put(`${base}.readout.confusion_matrix.${i}.${j}`, v);
                }
              });
            }
          });
        }
      }
      if (Array.isArray(props.benchmarks)) {
        for (const bench of props.benchmarks) {
          if (!isObject(bench)) continue;
          const bp = `${base}.benchmarks.${String(bench.protocol)}`;
          put(`${bp}.fidelity`, datumValue(bench.fidelity));
          put(`${bp}.error`, datumValue(bench.error));
        }
      }
    }
  }

  // --- gates (keyed by name@qubits so order does not matter) ---
  if (Array.isArray(d.gates)) {
    for (const g of d.gates) {
      if (!isObject(g)) continue;
      const qubits = Array.isArray(g.qubits) ? g.qubits.map(String) : [];
      const key = `${String(g.name)}@${qubits.join(",")}`;
      const base = `gates.${key}`;
      put(`${base}.fidelity`, datumValue(g.fidelity));
      put(`${base}.error`, datumValue(g.error));
      put(`${base}.duration`, datumValue(g.duration));
      if (Array.isArray(g.benchmarks)) {
        for (const bench of g.benchmarks) {
          if (!isObject(bench)) continue;
          const bp = `${base}.benchmarks.${String(bench.protocol)}`;
          put(`${bp}.fidelity`, datumValue(bench.fidelity));
          put(`${bp}.error`, datumValue(bench.error));
        }
      }
    }
  }

  // --- defcals (numeric params only, keyed by gate@qubits) ---
  if (Array.isArray(d.defcals)) {
    for (const dc of d.defcals) {
      if (!isObject(dc)) continue;
      const qubits = Array.isArray(dc.qubits) ? dc.qubits.map(String) : [];
      const key = `${String(dc.gate)}@${qubits.join(",")}`;
      const base = `defcals.${key}.params`;
      if (isObject(dc.params)) {
        for (const [pk, pv] of Object.entries(dc.params)) {
          if (typeof pv === "boolean") continue;
          if (typeof pv === "number") put(`${base}.${pk}`, pv);
        }
      }
    }
  }

  return out;
}

function collectLabels(doc: OqCalDocument): Map<string, string> {
  const out = new Map<string, string>();
  const put = (path: string, datum: unknown): void => {
    for (const field of LABELS) {
      const label = datumLabel(datum, field);
      if (label !== null) out.set(`${path}.${field}`, label);
    }
  };
  const d = doc as unknown as Record<string, unknown>;

  const agg = d.aggregates;
  if (isObject(agg)) {
    if (isObject(agg.qubits)) {
      put("aggregates.qubits.t1", agg.qubits.t1);
      put("aggregates.qubits.t2", agg.qubits.t2);
      put("aggregates.qubits.t2_echo", agg.qubits.t2_echo);
    }
    if (isObject(agg.readout)) {
      put("aggregates.readout.fidelity", agg.readout.fidelity);
      put("aggregates.readout.duration", agg.readout.duration);
    }
    for (const gname of ["gates_1q", "gates_2q"] as const) {
      const g = agg[gname];
      if (isObject(g)) {
        put(`aggregates.${gname}.fidelity`, g.fidelity);
        put(`aggregates.${gname}.error`, g.error);
        put(`aggregates.${gname}.duration`, g.duration);
      }
    }
    if (isObject(agg.ops)) {
      for (const [op, datum] of Object.entries(agg.ops)) put(`aggregates.ops.${op}`, datum);
    }
  }

  if (isObject(d.qubits)) {
    for (const [ref, props] of Object.entries(d.qubits)) {
      if (!isObject(props)) continue;
      const base = `qubits.${ref}`;
      put(`${base}.t1`, props.t1);
      put(`${base}.t2`, props.t2);
      put(`${base}.t2_echo`, props.t2_echo);
      put(`${base}.frequency_01`, props.frequency_01);
      put(`${base}.anharmonicity`, props.anharmonicity);
      if (isObject(props.readout)) {
        put(`${base}.readout.fidelity`, props.readout.fidelity);
        put(`${base}.readout.duration`, props.readout.duration);
      }
      if (Array.isArray(props.benchmarks)) {
        for (const bench of props.benchmarks) {
          if (!isObject(bench)) continue;
          const bp = `${base}.benchmarks.${String(bench.protocol)}`;
          put(`${bp}.fidelity`, bench.fidelity);
          put(`${bp}.error`, bench.error);
        }
      }
    }
  }

  if (Array.isArray(d.gates)) {
    for (const g of d.gates) {
      if (!isObject(g)) continue;
      const qubits = Array.isArray(g.qubits) ? g.qubits.map(String) : [];
      const key = `${String(g.name)}@${qubits.join(",")}`;
      const base = `gates.${key}`;
      put(`${base}.fidelity`, g.fidelity);
      put(`${base}.error`, g.error);
      put(`${base}.duration`, g.duration);
      if (Array.isArray(g.benchmarks)) {
        for (const bench of g.benchmarks) {
          if (!isObject(bench)) continue;
          const bp = `${base}.benchmarks.${String(bench.protocol)}`;
          put(`${bp}.fidelity`, bench.fidelity);
          put(`${bp}.error`, bench.error);
        }
      }
    }
  }

  return out;
}

function statusEntry(path: string, a: string | null, b: string | null): DiffEntry | null {
  if (a === b) return null;
  return {
    path,
    a_value: null,
    b_value: null,
    abs_change: null,
    rel_change: null,
    significance: "major",
    a_status: a,
    b_status: b,
  };
}

export function diff(a: OqCalDocument, b: OqCalDocument): OqCalDiff {
  const sa = collectScalars(a);
  const sb = collectScalars(b);
  const statusA = collectLabels(a);
  const statusB = collectLabels(b);
  const result = new OqCalDiff();
  const paths = [...new Set([...sa.keys(), ...sb.keys()])].sort();
  for (const path of paths) {
    const e = entry(path, sa.has(path) ? (sa.get(path) as number) : null, sb.has(path) ? (sb.get(path) as number) : null);
    if (e !== null) result.entries.push(e);
  }
  const statusPaths = [...new Set([...statusA.keys(), ...statusB.keys()])].sort();
  for (const path of statusPaths) {
    const e = statusEntry(path, statusA.get(path) ?? null, statusB.get(path) ?? null);
    if (e !== null) result.entries.push(e);
  }
  result.entries.sort((x, y) => (x.path < y.path ? -1 : x.path > y.path ? 1 : 0));
  return result;
}
