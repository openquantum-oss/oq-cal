/* eslint-disable */
/**
 * This file was automatically generated from spec/schema/oq-cal-0.1.schema.json.
 * DO NOT EDIT BY HAND. Run `npm run generate` to regenerate.
 */

/**
 * Physical-qubit reference, OpenQASM style: a dollar sign followed by the integer index.
 */
export type QubitRef = string;
/**
 * SI-canonical unit. Allowed: s, Hz, dimensionless (base SI units only; no prefixes).
 */
export type Unit = "s" | "Hz" | "dimensionless";
export type Status = "good" | "approximate" | "stale" | "bad" | "unmeasured";
/**
 * Readout confusion matrix. Rows index prepared state, columns index assigned state; rows sum to ~1.
 *
 * @minItems 2
 */
export type ConfusionMatrix = [
  [number, number, ...number[]],
  [number, number, ...number[]],
  ...[number, number, ...number[]][]
];

/**
 * A vendor-neutral JSON interchange format for QPU calibration and characterization data, version 0.1.
 */
export interface OqCalDeviceCalibrationDocument {
  "oq-cal": Header;
  device: Device;
  snapshot: Snapshot;
  aggregates?: Aggregates;
  /**
   * Per-qubit characterization, keyed by $n physical-qubit id.
   */
  qubits?: {
    [k: string]: QubitProperties;
  };
  gates?: GateEntry[];
  defcals?: Defcal[];
  /**
   * Verbatim source payloads keyed by source name. Conversion into oq-cal is never lossy.
   */
  extensions?: {
    [k: string]: unknown;
  };
  [k: string]: unknown;
}
/**
 * The versioned schema header.
 */
export interface Header {
  name: "oq-cal.device_calibration";
  version: string;
}
/**
 * Which machine this document describes.
 */
export interface Device {
  id: string;
  vendor?: string;
  model?: string;
  num_qubits?: number;
  /**
   * Map from $n physical-qubit id to vendor-native label (e.g. "qA4").
   */
  qubit_labels?: {
    [k: string]: string;
  };
  enabled_qubits?: QubitRef[];
  /**
   * Optional directed connectivity as ordered [$i, $j] pairs.
   */
  coupling_map?: [QubitRef, QubitRef][];
  [k: string]: unknown;
}
/**
 * When and from where this document was captured.
 */
export interface Snapshot {
  id?: string | null;
  /**
   * ISO-8601 timestamp of when the snapshot was captured.
   */
  captured_at?: string | null;
  source: string;
  source_schema?: string | null;
  [k: string]: unknown;
}
/**
 * Device-level medians and averages when per-qubit data is unavailable.
 */
export interface Aggregates {
  qubits?: {
    t1?: Datum;
    t2?: Datum;
    t2_echo?: Datum;
    [k: string]: unknown;
  };
  readout?: {
    fidelity?: Datum;
    duration?: Datum;
    [k: string]: unknown;
  };
  gates_1q?: {
    fidelity?: Datum;
    error?: Datum;
    duration?: Datum;
    [k: string]: unknown;
  };
  gates_2q?: {
    fidelity?: Datum;
    error?: Datum;
    duration?: Datum;
    [k: string]: unknown;
  };
  /**
   * Durations of elementary operations, e.g. reset_duration.
   */
  ops?: {
    [k: string]: Datum;
  };
  [k: string]: unknown;
}
/**
 * A single measured value. Only value+unit are required; everything else is optional.
 */
export interface Datum {
  value: number;
  unit: Unit;
  std_error?: number;
  err_minus?: number;
  err_plus?: number;
  median?: number;
  method?: string;
  /**
   * Mathematical quantity this number is. Recommended: average_gate_fidelity, process_fidelity, state_fidelity, readout_fidelity, assignment_error, average_gate_error, rb_decay. Other strings are valid. method names the protocol; metric names the quantity.
   */
  metric?: string;
  status?: Status;
  updated_at?: string | null;
  [k: string]: unknown;
}
/**
 * Per-qubit characterization.
 */
export interface QubitProperties {
  t1?: Datum;
  t2?: Datum;
  t2_echo?: Datum;
  frequency_01?: Datum;
  anharmonicity?: Datum;
  readout?: Readout;
  benchmarks?: Benchmark[];
  [k: string]: unknown;
}
export interface Readout {
  fidelity?: Datum;
  duration?: Datum;
  confusion_matrix?: ConfusionMatrix;
  classifier?: Classifier;
  [k: string]: unknown;
}
/**
 * Readout discriminator parameters.
 */
export interface Classifier {
  type?: string;
  projection?: number[];
  threshold?: number;
  status?: string;
  [k: string]: unknown;
}
/**
 * A protocol-level benchmark result (e.g. randomized benchmarking) attached to a qubit, pair, or gate.
 */
export interface Benchmark {
  protocol: string;
  fidelity?: Datum;
  error?: Datum;
  qubits?: QubitRef[];
  [k: string]: unknown;
}
/**
 * A characterized gate on specific qubits.
 */
export interface GateEntry {
  /**
   * stdgates vocabulary where possible (x, sx, rz, cz, ...); native/benchmark names allowed otherwise.
   */
  name: string;
  /**
   * @minItems 1
   */
  qubits: [QubitRef, ...QubitRef[]];
  fidelity?: Datum;
  error?: Datum;
  duration?: Datum;
  benchmarks?: Benchmark[];
  [k: string]: unknown;
}
/**
 * Per-gate pulse and control parameters, named after OpenQASM's defcal.
 */
export interface Defcal {
  gate: string;
  /**
   * @minItems 1
   */
  qubits: [QubitRef, ...QubitRef[]];
  /**
   * Pulse parameters. SI-suffixed keys (duration_s, frequency_hz, integration_time_s) carry base-SI values; dimensionless control params (amp, motzoi) carry bare numbers.
   */
  params?: {
    [k: string]: unknown;
  };
  [k: string]: unknown;
}
