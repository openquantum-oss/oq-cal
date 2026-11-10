// Diff-engine tests. Mirrors python/tests/test_diff.py (thresholds, keying,
// classification, summary).

import { describe, it, expect } from "vitest";
import { diff, MAJOR_REL, MINOR_REL } from "../src/diff.js";
import type { DiffEntry, OqCalDiff } from "../src/diff.js";
import type { OqCalDocument } from "../src/types.js";

function doc(parts: Partial<Record<string, unknown>> = {}): OqCalDocument {
  return {
    "oq-cal": { name: "oq-cal.device_calibration", version: "0.1" },
    device: { id: "synthetic:test", num_qubits: 4 },
    snapshot: { source: "synthetic" },
    ...parts,
  } as unknown as OqCalDocument;
}

function s(value: number) {
  return { value, unit: "s" };
}
function dl(value: number) {
  return { value, unit: "dimensionless" };
}

function entryFor(d: OqCalDiff, path: string): DiffEntry {
  const e = d.entries.find((x) => x.path === path);
  if (!e) throw new Error(`no diff entry for ${path}; have ${d.entries.map((x) => x.path)}`);
  return e;
}

describe("diff", () => {
  it("t1 major drop", () => {
    const a = doc({ qubits: { $0: { t1: s(100e-6) } } });
    const b = doc({ qubits: { $0: { t1: s(70e-6) } } });
    const e = entryFor(diff(a, b), "qubits.$0.t1");
    expect(e.a_value).toBeCloseTo(100e-6);
    expect(e.b_value).toBeCloseTo(70e-6);
    expect(e.rel_change!).toBeCloseTo(-0.3);
    expect(e.significance).toBe("major");
  });

  it("small fidelity change is noise", () => {
    const a = doc({ gates: [{ name: "x", qubits: ["$0"], fidelity: dl(0.99) }] });
    const b = doc({ gates: [{ name: "x", qubits: ["$0"], fidelity: dl(0.9801) }] });
    const e = entryFor(diff(a, b), "gates.x@$0.fidelity");
    expect(Math.abs(e.rel_change!)).toBeCloseTo(0.01, 6);
    expect(e.significance).toBe("noise");
  });

  it("minor boundary", () => {
    const a = doc({ qubits: { $0: { t1: s(100.0) } } });
    const b = doc({ qubits: { $0: { t1: s(100.0 * (1 + MINOR_REL + 0.01)) } } });
    expect(entryFor(diff(a, b), "qubits.$0.t1").significance).toBe("minor");
  });

  it("major boundary", () => {
    const a = doc({ qubits: { $0: { t1: s(100.0) } } });
    const b = doc({ qubits: { $0: { t1: s(100.0 * (1 + MAJOR_REL + 0.01)) } } });
    expect(entryFor(diff(a, b), "qubits.$0.t1").significance).toBe("major");
  });

  it("added qubit datum is major", () => {
    const a = doc({ qubits: { $0: { t1: s(100e-6) } } });
    const b = doc({ qubits: { $0: { t1: s(100e-6) }, $1: { t1: s(90e-6) } } });
    const e = entryFor(diff(a, b), "qubits.$1.t1");
    expect(e.a_value).toBeNull();
    expect(e.b_value).toBeCloseTo(90e-6);
    expect(e.rel_change).toBeNull();
    expect(e.significance).toBe("major");
  });

  it("removed datum is major", () => {
    const a = doc({ qubits: { $0: { t1: s(100e-6), t2: s(50e-6) } } });
    const b = doc({ qubits: { $0: { t1: s(100e-6) } } });
    const e = entryFor(diff(a, b), "qubits.$0.t2");
    expect(e.a_value).toBeCloseTo(50e-6);
    expect(e.b_value).toBeNull();
    expect(e.significance).toBe("major");
  });

  it("unchanged datum is noise", () => {
    const a = doc({ qubits: { $0: { t1: s(100e-6) } } });
    const b = doc({ qubits: { $0: { t1: s(100e-6) } } });
    const e = entryFor(diff(a, b), "qubits.$0.t1");
    expect(e.significance).toBe("noise");
    expect(e.abs_change).toBe(0);
  });

  it("defcal params compared numerically; non-numeric ignored", () => {
    const a = doc({ defcals: [{ gate: "x", qubits: ["$0"], params: { amp: 0.2, label: "p" } }] });
    const b = doc({ defcals: [{ gate: "x", qubits: ["$0"], params: { amp: 0.3, label: "p" } }] });
    const d = diff(a, b);
    const e = entryFor(d, "defcals.x@$0.params.amp");
    expect(e.rel_change!).toBeCloseTo(0.5);
    expect(e.significance).toBe("major");
    expect(d.entries.some((x) => x.path.endsWith("params.label"))).toBe(false);
  });

  it("gates keyed by name@qubits resist reorder", () => {
    const g1 = { name: "x", qubits: ["$0"], error: dl(0.001) };
    const g2 = { name: "cz", qubits: ["$0", "$1"], error: dl(0.01) };
    const a = doc({ gates: [g1, g2] });
    const b = doc({ gates: [g2, g1] });
    const d = diff(a, b);
    expect(d.entries.every((e) => e.significance === "noise")).toBe(true);
    expect(entryFor(d, "gates.x@$0.error")).toBeTruthy();
    expect(entryFor(d, "gates.cz@$0,$1.error")).toBeTruthy();
  });

  it("summary counts and worst offenders", () => {
    const a = doc({ qubits: { $0: { t1: s(100e-6) }, $1: { t1: s(100e-6) } } });
    const b = doc({ qubits: { $0: { t1: s(50e-6) }, $1: { t1: s(96e-6) } } });
    const d = diff(a, b);
    expect(d.counts.major).toBe(1);
    expect(d.counts.noise).toBe(1);
    expect(d.worstOffenders(1)[0]!.path).toBe("qubits.$0.t1");
    const sm = d.summary();
    expect(sm.total).toBe(2);
    expect(sm.counts.major).toBe(1);
  });

  it("status change is major and does not outrank a value change", () => {
    const a = doc({ qubits: { $0: { t1: { value: 1e-5, unit: "s", status: "good" } } } });
    const b = doc({ qubits: { $0: { t1: { value: 2e-5, unit: "s", status: "approximate" } } } });
    const d = diff(a, b);
    const status = entryFor(d, "qubits.$0.t1.status");
    expect(status.significance).toBe("major");
    expect(status.a_status).toBe("good");
    expect(status.b_status).toBe("approximate");
    expect(status.a_value).toBeNull();
    expect(status.rel_change).toBeNull();
    expect(d.worstOffenders(1)[0]!.path).toBe("qubits.$0.t1");
  });

  it("metric and method changes are major when the number is unchanged", () => {
    const fidelity = (metric: string, method: string) => ({
      value: 0.99,
      unit: "dimensionless",
      method,
      metric,
    });
    const a = doc({
      gates: [{ name: "x", qubits: ["$0"], fidelity: fidelity("process_fidelity", "rb") }],
    });
    const b = doc({
      gates: [
        {
          name: "x",
          qubits: ["$0"],
          fidelity: fidelity("average_gate_fidelity", "readout"),
        },
      ],
    });
    const d = diff(a, b);
    const metric = entryFor(d, "gates.x@$0.fidelity.metric");
    const method = entryFor(d, "gates.x@$0.fidelity.method");
    expect(metric.significance).toBe("major");
    expect(metric.a_status).toBe("process_fidelity");
    expect(metric.b_status).toBe("average_gate_fidelity");
    expect(metric.a_value).toBeNull();
    expect(method.a_status).toBe("rb");
    expect(method.b_status).toBe("readout");
    const value = entryFor(d, "gates.x@$0.fidelity");
    expect(value.significance).toBe("noise");
    expect(value.rel_change).toBe(0);
  });

  it("unchanged status is not an entry", () => {
    const t1 = { value: 1e-5, unit: "s", status: "good" };
    const d = diff(doc({ qubits: { $0: { t1 } } }), doc({ qubits: { $0: { t1: { ...t1 } } } }));
    expect(d.entries.some((e) => e.path.endsWith(".status"))).toBe(false);
    expect(d.counts.major).toBe(0);
  });

  it("zero baseline -> rel undefined -> major if abs change nonzero", () => {
    const a = doc({ qubits: { $0: { anharmonicity: { value: 0.0, unit: "Hz" } } } });
    const b = doc({ qubits: { $0: { anharmonicity: { value: -2e8, unit: "Hz" } } } });
    const e = entryFor(diff(a, b), "qubits.$0.anharmonicity");
    expect(e.rel_change).toBeNull();
    expect(e.significance).toBe("major");
  });
});
