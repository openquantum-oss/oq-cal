// Braket exporter tests: projection of an oq-cal document onto the Braket
// standardized-properties v1 shape, and a structural round-trip through the
// importer (import -> export -> re-import) on the per-qubit IQM vector.

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import { describe, it, expect } from "vitest";
import { toBraketStandardized } from "../src/exporters/braket.js";
import { fromBraketStandardized } from "../src/importers/braket.js";
import type { OqCalDocument } from "../src/types.js";

const here = dirname(fileURLToPath(import.meta.url));
const DOCS = resolve(here, "../../fixtures/oq-cal-docs");

function load(name: string): OqCalDocument {
  return JSON.parse(readFileSync(resolve(DOCS, name), "utf-8")) as OqCalDocument;
}

describe("toBraketStandardized", () => {
  it("emits the v1 schema header", () => {
    const out = toBraketStandardized(load("valid_per_qubit.json")) as Record<string, unknown>;
    expect(out.braketSchemaHeader).toEqual({
      name: "braket.device_schema.standardized_gate_model_qpu_device_properties",
      version: "1",
    });
  });

  it("projects readout fidelity + confusion-matrix off-diagonals", () => {
    const out = toBraketStandardized(load("valid_per_qubit.json")) as Record<string, unknown>;
    const oqp = out.oneQubitProperties as Record<string, { oneQubitFidelity: { fidelityType: { name: string } }[] }>;
    const names = oqp["0"]!.oneQubitFidelity.map((f) => f.fidelityType.name);
    expect(names).toContain("READOUT");
    expect(names).toContain("READOUT_ERROR_0_TO_1");
    expect(names).toContain("READOUT_ERROR_1_TO_0");
  });

  it("does not invert an unlabeled gate error into a fidelity", () => {
    const out = toBraketStandardized(load("valid_per_qubit.json")) as Record<string, unknown>;
    const tqp = out.twoQubitProperties as Record<
      string,
      { twoQubitGateFidelity: { gateName: string; fidelityType: { name: string }; fidelity: number }[] }
    >;
    const names = tqp["0-1"]!.twoQubitGateFidelity.map((f) => f.fidelityType.name);
    expect(names).not.toContain("RANDOMIZED_BENCHMARKING");
    expect(names).toContain("INTERLEAVED_RANDOMIZED_BENCHMARKING");
  });

  it("export output re-imports without throwing", () => {
    const exported = toBraketStandardized(load("valid_per_qubit.json"));
    const reimported = fromBraketStandardized(exported);
    expect((reimported as unknown as Record<string, unknown>)["oq-cal"]).toBeTruthy();
  });
});
