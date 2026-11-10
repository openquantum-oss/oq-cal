// Fictional Lumen importer behavior. Mirrors
// python/tests/test_importers_boulder_opal.py. Values are invented.

import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { diff } from "../src/diff.js";
import { fromBoulderOpal } from "../src/importers/boulder-opal.js";
import type { OqCalDocument } from "../src/types.js";

const FIXTURES = resolve(dirname(fileURLToPath(import.meta.url)), "../../fixtures/sources/boulder-opal");

function load(name: string): OqCalDocument {
  return fromBoulderOpal(JSON.parse(readFileSync(resolve(FIXTURES, name), "utf-8")));
}

function defcal(doc: OqCalDocument, gate: string, qubits: string[]) {
  const found = (doc.defcals ?? []).find(
    (d) => d.gate === gate && d.qubits.join(",") === qubits.join(","),
  );
  if (!found) throw new Error(`missing defcal ${gate} ${qubits}`);
  return found;
}

describe("fictional lumen boulder opal", () => {
  it("falls back to components and rewrites the drive frequency", () => {
    const doc = load("synthetic_lumen_components.json");
    expect(doc.device.id).toBe("lumen-demo-4");
    expect(doc.device.vendor).toBeUndefined();
    expect(doc.device.num_qubits).toBe(3);
    expect(doc.device.qubit_labels).toEqual({ $0: "q0", $1: "q1", $2: "q2" });
    expect(doc.device.enabled_qubits).toEqual(["$0", "$1"]);
    expect(doc.snapshot.captured_at).toBe("2026-03-01T12:00:00+00:00");
    expect(doc.gates).toBeUndefined();
    expect(doc.device.coupling_map).toBeUndefined();

    const q0 = doc.qubits!["$0"]!;
    expect(q0.t1!.value).toBeCloseTo(2e-5, 12);
    expect(q0.t1!.err_minus).toBeCloseTo(4e-7, 12);
    expect(q0.t1!.status).toBe("good");
    expect(q0.t2).toBeUndefined();
    expect(q0.readout!.confusion_matrix).toEqual([
      [0.9, 0.1],
      [0.25, 0.75],
    ]);
    expect(defcal(doc, "x", ["$0"]).params!.frequency_hz).toBe(4500000000);
    expect(defcal(doc, "measure", ["$0"]).params!.frequency_hz).toBe(7000000000);
    expect(defcal(doc, "measure", ["$0"]).params!.program).toBe("OPENQASM 3.0; // fictional");
    expect(doc.qubits!["$2"]!.t1!.value).toBeCloseTo(1.1e-5, 12);
  });

  it("prefers qubit_cal and omits null measurements", () => {
    const doc = load("synthetic_lumen_qubit_cal.json");
    expect(doc.device.num_qubits).toBe(3);
    expect(doc.device.enabled_qubits).toEqual(["$0", "$1"]);
    expect(doc.snapshot.captured_at).toBe("2026-04-15T09:30:00+00:00");
    expect(Object.keys(doc.qubits ?? {}).sort()).toEqual(["$0", "$2"]);
    const q0 = doc.qubits!["$0"]!;
    expect(q0.t1!.value).toBeCloseTo(4e-5, 12);
    expect(q0.t1!.err_minus).toBeCloseTo(1e-6, 12);
    expect(q0.t1!.status).toBe("approximate");
    expect(q0.frequency_01!.value).toBe(4600000000);
    expect(q0.anharmonicity).toBeUndefined();
    expect(defcal(doc, "x", ["$0"]).params!.frequency_hz).toBe(4600000000);
    expect(defcal(doc, "measure", ["$0"]).params!.frequency_hz).toBe(7100000000);
    expect(doc.qubits!["$2"]!.t1!.status).toBe("good");
  });

  it("records a T1 move and a status change", () => {
    const report = diff(
      load("synthetic_lumen_components.json"),
      load("synthetic_lumen_qubit_cal.json"),
    );
    const t1 = report.entries.find((e) => e.path === "qubits.$0.t1");
    expect(t1?.significance).toBe("major");
    expect(t1?.rel_change).toBeCloseTo(1, 6);
    const status = report.entries.find((e) => e.path === "qubits.$0.t1.status");
    expect(status?.a_status).toBe("good");
    expect(status?.b_status).toBe("approximate");
    const ranked = report.worstOffenders(report.entries.length).map((e) => e.path);
    expect(ranked.indexOf("qubits.$0.t1")).toBeLessThan(ranked.indexOf("qubits.$0.t1.status"));
  });
});
