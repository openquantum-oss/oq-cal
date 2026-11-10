// Tests for convert-time identity/provenance overrides (feedback 001 + 002) and
// the dead-element sentinel convention (feedback 003) in the Braket importer.
// Mirrors the Python unit tests in python/tests/test_importers_braket.py.

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import { describe, it, expect } from "vitest";
import { fromBraketStandardized } from "../src/importers/braket.js";

const here = dirname(fileURLToPath(import.meta.url));
const SRC = resolve(here, "../../fixtures/sources/braket");

function load(name: string): object {
  return JSON.parse(readFileSync(resolve(SRC, name), "utf-8"));
}

type Datum = { value: number; status?: string; std_error?: number };
type Qubit = {
  t1?: Datum;
  t2?: Datum;
  t2_echo?: Datum;
  readout?: { fidelity?: Datum };
  benchmarks?: { fidelity?: Datum }[];
};
type Gate = { fidelity?: Datum; error?: Datum };
type Doc = {
  device: { id: string; vendor?: string; model?: string };
  snapshot: { captured_at?: string; id?: string };
  qubits?: Record<string, Qubit>;
  gates?: Gate[];
};

function unmeasuredQubits(doc: Doc): Set<string> {
  const out = new Set<string>();
  for (const [ref, qp] of Object.entries(doc.qubits ?? {})) {
    const datums: (Datum | undefined)[] = [qp.t1, qp.t2, qp.t2_echo, qp.readout?.fidelity];
    for (const bm of qp.benchmarks ?? []) datums.push(bm.fidelity);
    if (datums.some((d) => d !== undefined && d.status === "unmeasured")) out.add(ref);
  }
  return out;
}

function unmeasuredGateEntries(doc: Doc): number {
  let n = 0;
  for (const g of doc.gates ?? []) {
    if (g.fidelity?.status === "unmeasured" || g.error?.status === "unmeasured") n += 1;
  }
  return n;
}

describe("braket identity / provenance overrides", () => {
  it("override kwargs win over source and the braket-device default", () => {
    const doc = fromBraketStandardized(load("raw_iqm-garnet.json"), {
      deviceId: "aws:iqm.garnet",
      vendor: "IQM",
      model: "Garnet",
      capturedAt: "2026-10-31T00:00:00+00:00",
      snapshotId: "demo-0001",
    }) as unknown as Doc;
    expect(doc.device.id).toBe("aws:iqm.garnet");
    expect(doc.device.vendor).toBe("IQM");
    expect(doc.device.model).toBe("Garnet");
    expect(doc.snapshot.captured_at).toBe("2026-10-31T00:00:00+00:00");
    expect(doc.snapshot.id).toBe("demo-0001");
  });

  it("device.id falls back to braket-device when omitted", () => {
    const doc = fromBraketStandardized(load("raw_iqm-garnet.json")) as unknown as Doc;
    expect(doc.device.id).toBe("braket-device");
  });
});

describe("braket dead-element sentinel", () => {
  it("cepheus-108 has exactly 4 sentinel qubits and 29 sentinel CZ edges", () => {
    const doc = fromBraketStandardized(
      load("braket_standardized_cepheus_108.json"),
    ) as unknown as Doc;
    expect([...unmeasuredQubits(doc)].sort()).toEqual(["$19", "$37", "$41", "$76"].sort());
    expect(unmeasuredGateEntries(doc)).toBe(29);
  });

  it("sentinel datum keeps value 0.5 and drops std_error", () => {
    const doc = fromBraketStandardized(
      load("braket_standardized_cepheus_108.json"),
    ) as unknown as Doc;
    const qp = doc.qubits!["$19"]!;
    const sentinel = (qp.benchmarks ?? []).find((b) => b.fidelity?.status === "unmeasured")!
      .fidelity!;
    expect(sentinel.value).toBe(0.5);
    expect(sentinel.std_error).toBeUndefined();
  });

  it("garnet and emerald import with zero unmeasured (no false positives)", () => {
    for (const name of ["raw_iqm-garnet.json", "raw_iqm-emerald.json"]) {
      const doc = fromBraketStandardized(load(name)) as unknown as Doc;
      expect(unmeasuredQubits(doc).size, name).toBe(0);
      expect(unmeasuredGateEntries(doc), name).toBe(0);
    }
  });
});
