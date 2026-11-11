# Contributing to Open Quantum Calibration Standard (oq-cal)

Issues and pull requests are welcome. The spec version is 0.1.

## Repository layout

oq-cal is a multi-language monorepo. The spec (`spec/`) and the shared test data
(`fixtures/`) live at the root; each language implementation gets its own top-level
directory. The reference library is Python, under `python/` (`pyproject.toml`, `src/`,
`tests/`). The TypeScript implementation is under `typescript/` and is checked
against the same conformance vectors. The shared fixtures are:

- `fixtures/sources/{braket,rigetti,ibm,boulder-opal,quam}/`: importer inputs;
- `fixtures/oq-cal-docs/`: hand-written `valid_*`/`invalid_*` oq-cal documents;
- `fixtures/conformance/`: cross-language test vectors (see below).

## Dev setup

Work from the `python/` directory:

```bash
cd python
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
pip install -e . --no-deps
```

## Running the tests

```bash
cd python
pytest -q
```

The suite covers the pydantic models, validation, the canonical JSON writer
(`oq_cal.io`), every importer/exporter, the CLI, an end-to-end integration suite that
round-trips the real fixture set under `fixtures/`, and the conformance suite
(`tests/test_conformance.py`). Please keep it green and add tests for any behaviour you
change.

## Conformance-vector policy

`fixtures/conformance/` pins the expected output of each importer so that every language
implementation can be checked against the same test data. Each `NN-name/` directory holds a
`manifest.json` (source payload, importer name, kwargs, description) and an
`expected.oq-cal.json` produced by running the reference importer through the canonical JSON
writer.

**Any behaviour change to a converter (or to the models / canonical serialization) requires
regenerating the vectors and reviewing the diff.** The diff is the human-readable record of
what your change does to real payloads. Regenerate with:

```bash
cd python
python scripts/generate_conformance.py        # rewrites fixtures/conformance/
git diff ../fixtures/conformance               # review every changed value
```

CI runs `generate_conformance.py --check` and fails if the committed vectors are stale, so a
converter change with unregenerated vectors will not merge. If a diff looks wrong, fix the
converter rather than committing the vector.

## Spec-change policy

The spec lives in **three places that must move together** in a single change:

1. `spec/specification.md`: the normative prose;
2. `spec/schema/oq-cal-0.1.schema.json`: the JSON Schema (the machine-readable authority);
3. `python/src/oq_cal/models.py`: the pydantic models that mirror the schema.

The bundled schema copy at `python/src/oq_cal/_schema/oq-cal-0.1.schema.json` **must stay
byte-identical** to `spec/schema/oq-cal-0.1.schema.json` (the `schema` CI job enforces this with
`cmp`). After editing the spec schema, copy it over:

```bash
cp spec/schema/oq-cal-0.1.schema.json python/src/oq_cal/_schema/oq-cal-0.1.schema.json
```

Backward-compatibility follows the spec's own versioning rules (see §12): within a MINOR
version you may only add OPTIONAL sections/fields. A change that alters required structure is
a MAJOR bump and ships a new schema file under `spec/schema/`.

## Documentation

The documentation site lives in `docs/` and is built with [MkDocs](https://www.mkdocs.org/)
and the Material theme; `mkdocs.yml` is at the repository root. The site single-sources the
normative spec: the Specification pages pull `spec/intro.md` and `spec/specification.md` in
verbatim via the include-markdown plugin, and the Python API pages are generated from source
docstrings by mkdocstrings. Documentation prose is never hand-duplicated from the spec.

Build and preview locally:

```bash
python -m venv docs/.venv
source docs/.venv/bin/activate
pip install -r docs/requirements.txt
pip install -e ./python                  # needed for the API reference
mkdocs serve                             # live preview at http://127.0.0.1:8000
mkdocs build --strict                    # must pass with no warnings
```

`mkdocs build --strict` must pass (no broken links or nav warnings). On pushes to `main`
that touch `docs/**`, `spec/**`, `mkdocs.yml`, `python/src/**`, or the workflow file,
`.github/workflows/docs.yml` builds the site and deploys it to GitHub Pages.

## PR flow

No CLA, no DCO sign-off required; just open a PR:

1. Branch from `main`.
2. Make your change, keeping the three spec artifacts in sync if you touch the format.
3. Run `pytest -q` locally; make sure CI is green.
4. Open the PR with a short description of what and why.

Keep PRs focused and commit messages lean.
