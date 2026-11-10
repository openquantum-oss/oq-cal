// One Braket entry point. The header name selects the schema reader.
// Standardized properties and Rigetti capabilities stay separate functions
// because a capabilities document can embed a standardized block, and each
// schema has its own version check.

import type { OqCalDocument } from "../types.js";
import {
  BraketSchemaError,
  SCHEMA_NAME,
  fromBraketStandardized,
  type BraketOptions,
} from "./braket.js";
import { RIGETTI_SCHEMA, fromBraketRigetti } from "./rigetti.js";

function headerName(payload: object): string | undefined {
  const header = (payload as { braketSchemaHeader?: unknown }).braketSchemaHeader;
  if (!header || typeof header !== "object" || !("name" in header)) return undefined;
  const name = (header as { name?: unknown }).name;
  return typeof name === "string" ? name : undefined;
}

export function fromBraket(payload: object, opts: BraketOptions = {}): OqCalDocument {
  const name = headerName(payload);
  if (name === SCHEMA_NAME) return fromBraketStandardized(payload, opts);
  if (name === RIGETTI_SCHEMA) return fromBraketRigetti(payload, opts);
  throw new BraketSchemaError(
    `unsupported Braket schema ${JSON.stringify(name)}; ` +
      `expected ${JSON.stringify(SCHEMA_NAME)} or ${JSON.stringify(RIGETTI_SCHEMA)}`,
  );
}
