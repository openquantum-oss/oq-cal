// Canonical JSON writer tests. Mirrors python/tests/test_io.py.

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import { describe, it, expect } from "vitest";
import { toCanonicalJson } from "../src/canonical.js";
import type { OqCalDocument } from "../src/types.js";

const here = dirname(fileURLToPath(import.meta.url));
const DOCS = resolve(here, "../../fixtures/oq-cal-docs");

function load(name: string): OqCalDocument {
  return JSON.parse(readFileSync(resolve(DOCS, name), "utf-8")) as OqCalDocument;
}

const doc = load("valid_full_depth.json");

describe("toCanonicalJson", () => {
  it("ends with exactly one trailing newline", () => {
    const out = toCanonicalJson(doc);
    expect(out.endsWith("}\n")).toBe(true);
    expect(out.endsWith("}\n\n")).toBe(false);
  });

  it("uses two-space indent for top-level keys", () => {
    const out = toCanonicalJson(doc);
    const lines = out.split("\n");
    expect(lines.some((l) => l.startsWith('  "oq-cal"'))).toBe(true);
    expect(lines.some((l) => l.startsWith('    "oq-cal"'))).toBe(false);
  });

  it("omits null/undefined fields (no literal null)", () => {
    expect(toCanonicalJson(doc).includes(": null")).toBe(false);
  });

  it("keeps JSON null inside extensions and omits null model fields", () => {
    const d = {
      "oq-cal": { name: "oq-cal.device_calibration", version: "0.1" },
      device: { id: "d", vendor: null },
      snapshot: { source: "test" },
      extensions: { boulder_opal: { qubit_cal: null, nested: { err_minus: null, value: 1 } } },
    } as unknown as OqCalDocument;
    const out = JSON.parse(toCanonicalJson(d)) as {
      device: { vendor?: string };
      extensions: { boulder_opal: { qubit_cal: null; nested: { err_minus: null; value: number } } };
    };
    expect(out.device.vendor).toBeUndefined();
    expect(out.extensions.boulder_opal.qubit_cal).toBeNull();
    expect(out.extensions.boulder_opal.nested.err_minus).toBeNull();
    expect(out.extensions.boulder_opal.nested.value).toBe(1);
  });

  it("round-trips structurally", () => {
    const out = toCanonicalJson(doc);
    const reparsed = JSON.parse(out) as OqCalDocument;
    expect(JSON.parse(toCanonicalJson(reparsed))).toEqual(JSON.parse(out));
  });

  it("is deterministic", () => {
    expect(toCanonicalJson(doc)).toBe(toCanonicalJson(doc));
  });

  it("keys follow model declaration order, not sorted order", () => {
    const data = JSON.parse(toCanonicalJson(doc)) as Record<string, unknown>;
    const keys = Object.keys(data);
    expect(keys.indexOf("oq-cal")).toBeLessThan(keys.indexOf("device"));
    expect(keys.indexOf("device")).toBeLessThan(keys.indexOf("snapshot"));
  });

  it("emits non-ASCII verbatim, not \\uXXXX-escaped", () => {
    const d = {
      "oq-cal": { name: "oq-cal.device_calibration", version: "0.1" },
      device: { id: "synthetic:µ-device", vendor: "Ωmega" },
      snapshot: { source: "test" },
    } as unknown as OqCalDocument;
    const out = toCanonicalJson(d);
    expect(out.includes("µ-device")).toBe(true);
    expect(out.includes("Ωmega")).toBe(true);
    expect(out.includes("\\u")).toBe(false);
  });

  it("preserves datum field order within a datum", () => {
    const d = {
      "oq-cal": { name: "oq-cal.device_calibration", version: "0.1" },
      device: { id: "x", num_qubits: 1 },
      snapshot: { source: "test" },
      qubits: {
        $0: {
          // deliberately scrambled input order; output must be value,unit,status
          t1: { status: "good", unit: "s", value: 1e-5 },
        },
      },
    } as unknown as OqCalDocument;
    const out = toCanonicalJson(d);
    const vi = out.indexOf('"value"');
    const ui = out.indexOf('"unit"');
    const si = out.indexOf('"status"');
    expect(vi).toBeLessThan(ui);
    expect(ui).toBeLessThan(si);
  });
});
