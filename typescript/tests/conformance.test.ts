// Conformance suite: the TS importers must reproduce the pinned cross-language
// vectors under fixtures/conformance/. For each manifest we run the named
// importer (mapping snake_case manifest kwargs to camelCase opts) and assert
// JSON.parse(toCanonicalJson(result)) deep-equals the parsed expected document.
//
// Structural (parsed) equality is the acceptance bar — JS and Python format some
// floats differently in text, but those parse to identical numbers.

import { readFileSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import { describe, it, expect } from "vitest";
import { getImporter } from "../src/registry.js";
import { toCanonicalJson } from "../src/canonical.js";

const here = dirname(fileURLToPath(import.meta.url));
const FIXTURES = resolve(here, "../../fixtures");
const CONFORMANCE = resolve(FIXTURES, "conformance");

function vectorDirs(): string[] {
  return readdirSync(CONFORMANCE, { withFileTypes: true })
    .filter((e) => e.isDirectory())
    .map((e) => e.name)
    .sort();
}

const DIRS = vectorDirs();

describe("conformance vectors", () => {
  it("has the expected number of vectors", () => {
    expect(DIRS.length).toBe(14);
  });

  for (const dir of DIRS) {
    it(dir, () => {
      const manifest = JSON.parse(
        readFileSync(resolve(CONFORMANCE, dir, "manifest.json"), "utf-8"),
      );
      const expected = JSON.parse(
        readFileSync(resolve(CONFORMANCE, dir, "expected.oq-cal.json"), "utf-8"),
      );
      const payload = JSON.parse(
        readFileSync(resolve(FIXTURES, manifest.source), "utf-8"),
      );
      const importer = getImporter(manifest.importer);
      const result = importer(payload, manifest.kwargs ?? {});
      const produced = JSON.parse(toCanonicalJson(result));
      expect(produced).toEqual(expected);
    });
  }
});
