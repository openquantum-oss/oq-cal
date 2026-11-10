// Cleaned, stable public type aliases over the generated schema types.
//
// json-schema-to-typescript derives the root interface name from the schema
// `title` ("oq-cal device calibration document" -> OqCalDeviceCalibrationDocument).
// The public surface promises `OqCalDocument`, so we alias it here. The nested
// section types already have clean names and are re-exported verbatim.

import type { OqCalDeviceCalibrationDocument } from "./generated/schema.js";

export type OqCalDocument = OqCalDeviceCalibrationDocument;

export type {
  Header,
  Device,
  Snapshot,
  Aggregates,
  Datum,
  QubitProperties,
  Readout,
  Classifier,
  Benchmark,
  GateEntry,
  Defcal,
  Unit,
  Status,
  QubitRef,
  ConfusionMatrix,
} from "./generated/schema.js";
