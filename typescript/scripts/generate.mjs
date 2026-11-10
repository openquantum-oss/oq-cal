// Generate TypeScript types and a runtime schema copy from the canonical
// JSON Schema at ../spec/schema/oq-cal-0.1.schema.json.
//
// Outputs (both committed, kept in sync by this script):
//   src/generated/schema.ts    - types via json-schema-to-typescript
//   src/generated/schema.json  - verbatim copy of the spec schema, loaded by
//                                Ajv at runtime (so validate() and the types
//                                share a single source of truth)
//
// Sync policy: the spec schema is the authority. Run `npm run generate` after
// any schema change and commit the regenerated outputs. CI runs the script and
// `git diff --exit-code` to guarantee the committed outputs match the schema.

import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import { compile } from "json-schema-to-typescript";

const here = dirname(fileURLToPath(import.meta.url));
const schemaPath = resolve(here, "../../spec/schema/oq-cal-0.1.schema.json");
const outDir = resolve(here, "../src/generated");
const tsOut = resolve(outDir, "schema.ts");
const jsonOut = resolve(outDir, "schema.json");

const schemaText = readFileSync(schemaPath, "utf-8");
const schema = JSON.parse(schemaText);

mkdirSync(outDir, { recursive: true });

// Runtime copy for Ajv: re-serialize with a stable 2-space indent + trailing
// newline so the committed file is deterministic regardless of the source's
// exact whitespace.
writeFileSync(jsonOut, JSON.stringify(schema, null, 2) + "\n", "utf-8");

const banner = `/* eslint-disable */
/**
 * This file was automatically generated from spec/schema/oq-cal-0.1.schema.json.
 * DO NOT EDIT BY HAND. Run \`npm run generate\` to regenerate.
 */`;

const ts = await compile(schema, "OqCalDocument", {
  bannerComment: banner,
  additionalProperties: true,
  style: { singleQuote: false, semi: true },
  declareExternallyReferenced: true,
  enableConstEnums: false,
});

writeFileSync(tsOut, ts, "utf-8");

console.log(`generated ${tsOut}`);
console.log(`generated ${jsonOut}`);
