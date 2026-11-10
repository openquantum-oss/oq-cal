// Validator tests. Mirrors python/tests/test_validate.py:
//   * every fixtures/oq-cal-docs/valid_*.json -> zero issues;
//   * each invalid_*.json -> at least one issue with the expected code;
//   * the semantic checks (SI units, $n bounds, confusion-matrix row sums,
//     std_error/err exclusivity + pairing).

import { readFileSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import { describe, it, expect } from "vitest";
import { validate } from "../src/validate.js";
import type { ValidationIssue } from "../src/validate.js";

const here = dirname(fileURLToPath(import.meta.url));
const DOCS = resolve(here, "../../fixtures/oq-cal-docs");

function load(name: string): unknown {
  return JSON.parse(readFileSync(resolve(DOCS, name), "utf-8"));
}

function errors(issues: ValidationIssue[]): ValidationIssue[] {
  return issues.filter((i) => i.severity === "error");
}

const validFiles = readdirSync(DOCS).filter((f) => f.startsWith("valid_") && f.endsWith(".json"));
const invalidFiles = readdirSync(DOCS).filter(
  (f) => f.startsWith("invalid_") && f.endsWith(".json"),
);

describe("valid fixtures", () => {
  for (const f of validFiles) {
    it(`${f} validates clean`, () => {
      expect(validate(load(f))).toEqual([]);
    });
  }
});

describe("invalid fixtures", () => {
  it("has fixtures to check", () => {
    expect(invalidFiles.length).toBeGreaterThan(0);
  });

  it("invalid_missing_header.json flags the missing header", () => {
    const errs = errors(validate(load("invalid_missing_header.json")));
    expect(errs.length).toBeGreaterThan(0);
    expect(errs.some((e) => e.message.includes("oq-cal") || e.path === "<root>")).toBe(true);
  });

  it("invalid_non_si_unit.json flags the non-SI units", () => {
    const errs = errors(validate(load("invalid_non_si_unit.json")));
    const messages = errs.map((e) => e.message).join(" ");
    expect(messages.includes("ns") || messages.includes("GHz")).toBe(true);
    expect(errs.some((e) => e.code === "non_si_unit" || e.path.includes("unit"))).toBe(true);
  });
});

describe("semantic checks", () => {
  const base = {
    "oq-cal": { name: "oq-cal.device_calibration", version: "0.1" },
    device: { id: "x", num_qubits: 1 },
    snapshot: { source: "test" },
  };

  it("qubit ref out of range", () => {
    const data = {
      ...base,
      device: { id: "x", num_qubits: 2 },
      qubits: { $5: { t1: { value: 1e-5, unit: "s" } } },
    };
    const errs = errors(validate(data));
    expect(errs.some((e) => e.code === "qubit_ref_out_of_range")).toBe(true);
    expect(errs.some((e) => e.message.includes("out of range"))).toBe(true);
  });

  it("std_error with asymmetric errors", () => {
    const data = {
      ...base,
      qubits: {
        $0: { t1: { value: 1e-5, unit: "s", std_error: 1e-7, err_minus: 1e-7, err_plus: 1e-7 } },
      },
    };
    const errs = errors(validate(data));
    expect(errs.some((e) => e.code === "std_error_with_asymmetric")).toBe(true);
    expect(errs.some((e) => e.message.includes("std_error"))).toBe(true);
  });

  it("unpaired err is an error", () => {
    const data = {
      ...base,
      qubits: { $0: { t1: { value: 1e-5, unit: "s", err_minus: 1e-7 } } },
    };
    const errs = errors(validate(data));
    expect(errs.some((e) => e.code === "unpaired_err")).toBe(true);
    expect(errs.some((e) => e.message.includes("err_minus and err_plus"))).toBe(true);
  });

  it("confusion-matrix row sum out of tolerance", () => {
    const data = {
      ...base,
      qubits: { $0: { readout: { confusion_matrix: [[0.9, 0.3], [0.1, 0.9]] } } },
    };
    const errs = errors(validate(data));
    expect(errs.some((e) => e.code === "confusion_matrix_row_sum")).toBe(true);
    expect(errs.some((e) => e.message.includes("confusion-matrix row"))).toBe(true);
  });

  it("good confusion matrix passes (within tol 0.02)", () => {
    const data = {
      ...base,
      qubits: { $0: { readout: { confusion_matrix: [[0.96, 0.04], [0.07, 0.93]] } } },
    };
    expect(errors(validate(data))).toEqual([]);
  });

  it("extensions subtree is not unit-checked", () => {
    const data = {
      ...base,
      extensions: { raw: { t1: { value: 18220, unit: "ns" } } },
    };
    expect(errors(validate(data))).toEqual([]);
  });

  it("accepts a parsed document object and a JSON string alike", () => {
    const data = {
      ...base,
      qubits: { $0: { t1: { value: 1e-5, unit: "s" } } },
    };
    expect(validate(data)).toEqual([]);
    expect(validate(JSON.stringify(data))).toEqual([]);
  });
});
