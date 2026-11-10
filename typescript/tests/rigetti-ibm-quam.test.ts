import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { BraketSchemaError } from "../src/importers/braket.js";
import { fromBraket } from "../src/importers/from-braket.js";
import { fromBraketRigetti } from "../src/importers/rigetti.js";
import { fromIbmProperties } from "../src/importers/ibm.js";
import { fromQuamState } from "../src/importers/quam.js";

const here = dirname(fileURLToPath(import.meta.url));
const sources = resolve(here, "../../fixtures/sources");

function load(path: string): object {
  return JSON.parse(readFileSync(resolve(sources, path), "utf-8"));
}

describe("braket dispatch", () => {
  it("selects the reader from braketSchemaHeader.name", () => {
    const standardized = fromBraket({
      braketSchemaHeader: {
        name: "braket.device_schema.standardized_gate_model_qpu_device_properties",
        version: "1",
      },
    });
    expect(standardized.snapshot?.source_schema).toContain(
      "standardized_gate_model_qpu_device_properties v1",
    );
    const rigetti = fromBraket(load("rigetti/synthetic_rigetti_capabilities.json"));
    expect(rigetti.snapshot?.source_schema).toContain("rigetti_device_capabilities v2");
    expect(() =>
      fromBraket({ braketSchemaHeader: { name: "nope", version: "1" } }),
    ).toThrow(BraketSchemaError);
  });
});

describe("rigetti capabilities", () => {
  it("keeps a one-based graph shifted and does not invent calibration", () => {
    const doc = fromBraketRigetti({
      braketSchemaHeader: {
        name: "braket.device_schema.rigetti.rigetti_device_capabilities",
        version: "2",
      },
      paradigm: {
        qubitCount: 2,
        connectivity: { connectivityGraph: { "1": ["2"], "2": ["1"] } },
      },
    });
    expect(doc.device.num_qubits).toBe(2);
    expect(doc.device.qubit_labels).toEqual({ $0: "1", $1: "2" });
    expect(doc.device.coupling_map).toEqual([
      ["$0", "$1"],
      ["$1", "$0"],
    ]);
    expect(doc.qubits).toBeUndefined();
    expect(doc.gates).toBeUndefined();
  });

  it("imports the fictional capabilities fixture without gate errors", () => {
    const doc = fromBraketRigetti(load("rigetti/synthetic_rigetti_capabilities.json"));
    expect(doc.device.num_qubits).toBe(3);
    expect(doc.gates).toBeUndefined();
    expect(doc.defcals?.[0]?.params).toEqual({ frequency_hz: 4500000000 });
    expect(doc.qubits?.$0?.readout?.fidelity?.metric).toBe("readout_fidelity");
  });

  it("copies a specs standard error only when the standardized value matches", () => {
    const doc = fromBraketRigetti({
      braketSchemaHeader: {
        name: "braket.device_schema.rigetti.rigetti_device_capabilities",
        version: "2",
      },
      paradigm: { qubitCount: 2, connectivity: { connectivityGraph: {} } },
      standardized: {
        braketSchemaHeader: {
          name: "braket.device_schema.standardized_gate_model_qpu_device_properties",
          version: "1",
        },
        oneQubitProperties: {
          "0": {
            T1: { value: 3.6e-5, unit: "S" },
            T2: { value: 2.1e-5, unit: "S", standardError: 9.0e-7 },
          },
          "1": { T1: { value: 1.0e-5, unit: "S" } },
        },
      },
      provider: {
        specs: {
          benchmarks: [
            {
              name: "FreeInversionRecovery",
              sites: [
                {
                  node_ids: [0],
                  characteristics: [{ name: "T1", value: 3.6e-5, error: 1.2e-6 }],
                },
                {
                  node_ids: [1],
                  characteristics: [{ name: "T1", value: 9.0e-5, error: 1.0e-6 }],
                },
              ],
            },
            {
              name: "FreeInductionDecay",
              sites: [
                {
                  node_ids: [0],
                  characteristics: [{ name: "T2", value: 2.1e-5, error: 1.7e-6 }],
                },
              ],
            },
          ],
        },
      },
    });
    expect(doc.qubits?.$0?.t1?.std_error).toBeCloseTo(1.2e-6, 12);
    expect(doc.qubits?.$0?.t2?.std_error).toBeCloseTo(9.0e-7, 12);
    expect(doc.qubits?.$1?.t1?.std_error).toBeUndefined();
  });
});

describe("ibm properties", () => {
  it("keeps cx direction and stores gate_error as an error", () => {
    const doc = fromIbmProperties(load("ibm/synthetic_fictional_transmon2.json"));
    expect(doc.device.id).toBe("fictional-transmon-2");
    expect(doc.device.coupling_map).toEqual([["$0", "$1"]]);
    expect(doc.qubits?.$0?.readout?.fidelity).toBeUndefined();
    expect(doc.qubits?.$0?.benchmarks?.[0]?.error?.metric).toBe("assignment_error");
    const x = doc.gates?.find((g) => g.name === "x");
    expect(x?.error?.metric).toBe("average_gate_error");
    expect(x?.error?.value).toBeCloseTo(0.0004, 12);
  });
});

describe("quam sample rate", () => {
  it("uses an explicit root rate and otherwise keeps 1 GS/s", () => {
    const doc = fromQuamState({
      sampling_rate: 2e9,
      qubits: {
        q0: {
          __class__: "lab.Transmon",
          id: 0,
          xy: { operations: { x180: { length: 32, amplitude: 0.2 } } },
        },
      },
    });
    expect(doc.defcals?.[0]?.params?.duration_s).toBeCloseTo(16e-9, 15);
  });
});
