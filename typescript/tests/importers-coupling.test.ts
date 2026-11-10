// Focused tests for coupling_map derivation in the TS importers. Mirrors the
// Python unit tests; the conformance suite separately proves byte-for-structure
// cross-language identity against the regenerated vectors.

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import { describe, it, expect } from "vitest";
import { fromBraketStandardized } from "../src/importers/braket.js";
import { fromBoulderOpal } from "../src/importers/boulder-opal.js";
import { fromQuamState } from "../src/importers/quam.js";

const here = dirname(fileURLToPath(import.meta.url));
const SRC = resolve(here, "../../fixtures/sources");

function load(rel: string): object {
  return JSON.parse(readFileSync(resolve(SRC, rel), "utf-8"));
}

function couplingMap(doc: unknown): string[][] | undefined {
  return (doc as { device: { coupling_map?: string[][] } }).device.coupling_map;
}

describe("coupling_map derivation", () => {
  it("braket garnet: 30 undirected -> 60 directed, sorted & symmetric", () => {
    const cm = couplingMap(fromBraketStandardized(load("braket/raw_iqm-garnet.json")));
    expect(cm).toBeDefined();
    expect(cm!.length).toBe(60);
    const nums = cm!.map(([a, b]) => [Number(a.slice(1)), Number(b.slice(1))] as [number, number]);
    const sorted = [...nums].sort((x, y) => (x[0] !== y[0] ? x[0] - y[0] : x[1] - y[1]));
    expect(nums).toEqual(sorted);
    const set = new Set(nums.map(([a, b]) => `${a},${b}`));
    expect([...set].every((p) => set.has(p.split(",").reverse().join(",")))).toBe(true);
  });

  it("braket cepheus: 193 -> 386", () => {
    const cm = couplingMap(fromBraketStandardized(load("braket/braket_standardized_cepheus_108.json")));
    expect(cm!.length).toBe(386);
  });

  it("braket emerald: 87 -> 174", () => {
    const cm = couplingMap(fromBraketStandardized(load("braket/raw_iqm-emerald.json")));
    expect(cm!.length).toBe(174);
  });

  it("braket aggregates-only (aqt, ionq): no coupling_map", () => {
    expect(couplingMap(fromBraketStandardized(load("braket/raw_aqt-ibex-q1.json")))).toBeUndefined();
    expect(
      couplingMap(fromBraketStandardized(load("braket/raw_ionq-forte-1.json"), { numQubits: 36 })),
    ).toBeUndefined();
  });

  it("boulder opal: 2q evidence -> both directions", () => {
    const cm = couplingMap(fromBoulderOpal(load("boulder-opal/synthetic_acme_transmon8.json")));
    expect(cm).toEqual([
      ["$0", "$1"],
      ["$1", "$0"],
    ]);
  });

  it("quam: one qubit_pair -> both directions", () => {
    const cm = couplingMap(fromQuamState(load("quam/synthetic_state.json")));
    expect(cm).toEqual([
      ["$0", "$1"],
      ["$1", "$0"],
    ]);
  });

  it("quam thin tree: no coupling_map", () => {
    expect(couplingMap(fromQuamState({ qubits: {} }))).toBeUndefined();
  });
});

describe("0-based qubit remapping", () => {
  type Dev = { device: { num_qubits?: number; qubit_labels?: Record<string, string> }; qubits?: Record<string, unknown> };

  it("braket garnet: 1-based source remapped to dense $0..$19 with labels", () => {
    const doc = fromBraketStandardized(load("braket/raw_iqm-garnet.json")) as unknown as Dev;
    expect(doc.device.num_qubits).toBe(20);
    expect(Object.keys(doc.qubits!).sort()).not.toContain("$20"); // no phantom qubit
    expect(doc.qubits!["$0"]).toBeDefined();
    expect(doc.qubits!["$19"]).toBeDefined();
    const labels = doc.device.qubit_labels!;
    expect(labels["$0"]).toBe("1");
    expect(labels["$19"]).toBe("20");
    expect(Object.keys(labels).length).toBe(20);
  });

  it("braket emerald: 1-based source remapped, labels recorded", () => {
    const doc = fromBraketStandardized(load("braket/raw_iqm-emerald.json")) as unknown as Dev;
    expect(doc.device.num_qubits).toBe(54);
    expect(doc.device.qubit_labels!["$0"]).toBe("1");
  });

  it("braket cepheus: already 0-based, kept verbatim, sparse gap preserved, no labels", () => {
    const doc = fromBraketStandardized(load("braket/braket_standardized_cepheus_108.json")) as unknown as Dev;
    expect(doc.device.num_qubits).toBe(108);
    expect(doc.device.qubit_labels).toBeUndefined();
    expect(doc.qubits!["$8"]).toBeUndefined(); // source key "8" absent -> stays sparse
    expect(doc.qubits!["$0"]).toBeDefined();
    expect(doc.qubits!["$107"]).toBeDefined();
  });
});
