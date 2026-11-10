// Importer registry keyed by the names used in the conformance manifests
// (fixtures/conformance/*/manifest.json). Each importer takes the raw payload
// plus a snake_case kwargs object (as written in the manifests); this module
// maps those to the camelCase options the public functions expect.

import type { OqCalDocument } from "./types.js";
import { fromBraket } from "./importers/from-braket.js";
import { fromBoulderOpal } from "./importers/boulder-opal.js";
import { fromIbmProperties } from "./importers/ibm.js";
import { fromQuamState } from "./importers/quam.js";

export type ManifestKwargs = Record<string, unknown>;
export type RegisteredImporter = (payload: object, kwargs: ManifestKwargs) => OqCalDocument;

// Snake_case manifest kwarg name -> camelCase option name.
const KWARG_ALIASES: Record<string, string> = {
  num_qubits: "numQubits",
  device_id: "deviceId",
  captured_at: "capturedAt",
  snapshot_id: "snapshotId",
};

function toOpts(kwargs: ManifestKwargs): Record<string, unknown> {
  const opts: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(kwargs)) {
    const alias = KWARG_ALIASES[k] ?? k;
    opts[alias] = v;
  }
  return opts;
}

export const IMPORTERS: Record<string, RegisteredImporter> = {
  braket: (payload, kwargs) => fromBraket(payload, toOpts(kwargs)),
  "boulder-opal": (payload, kwargs) => fromBoulderOpal(payload, toOpts(kwargs)),
  "ibm-properties": (payload, kwargs) => fromIbmProperties(payload, toOpts(kwargs)),
  "quam-state": (payload, kwargs) => fromQuamState(payload, toOpts(kwargs)),
};

export function getImporter(name: string): RegisteredImporter {
  const imp = IMPORTERS[name];
  if (imp === undefined) throw new Error(`no importer registered under '${name}'`);
  return imp;
}
