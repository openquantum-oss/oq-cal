# Python API

The reference library implements the [specification](../spec/introduction.md):
pydantic models that mirror the JSON Schema, a two-layer validator, a canonical JSON writer,
a drift engine, and a registry of importers and exporters. These pages are generated
from the docstrings in `python/src/oq_cal/`.

## Top-level exports

The most-used names are re-exported from the `oq_cal` package root:

```python
from oq_cal import (
    OqCalDocument, Datum, Device, Snapshot, Header,   # models
    QubitProperties, Readout, Classifier, Benchmark,
    GateEntry, Defcal, Aggregates, Unit, Status,
    validate, ValidationIssue,                        # validation
    to_canonical_json,                                # serialization
    register_importer, register_exporter,             # registry
    get_importer, get_exporter, list_formats, load_all,
    SPEC_VERSION, __version__,
)
```

## Sections

| Page | Module | Contents |
|---|---|---|
| [Models](models.md) | `oq_cal.models` | the document model: `OqCalDocument` and its parts |
| [Validation](validate.md) | `oq_cal.validate` | `validate`, `ValidationIssue`, `load_schema` |
| [Serialization](io.md) | `oq_cal.io` | `to_canonical_json`, the canonical on-disk form |
| [Diff](diff.md) | `oq_cal.diff` | the drift engine: `diff`, `OqCalDiff`, `DiffEntry` |
| [Importers](importers.md) | `oq_cal.importers.*` | Braket, Boulder Opal, QUAM, Qiskit → oq-cal |
| [Exporters](exporters.md) | `oq_cal.exporters.*` | oq-cal → Qiskit `Target`, Braket |

## Converter signatures at a glance

The importer and exporter entry points, with their optional keyword arguments:

```python
from oq_cal.importers.braket import from_braket
from oq_cal.importers.boulder_opal import from_boulder_opal
from oq_cal.importers.quam   import from_quam_state
from oq_cal.importers.qiskit import from_qiskit_target
from oq_cal.exporters.qiskit import to_qiskit_target
from oq_cal.exporters.braket import to_braket
```

See the [converting guides](../guides/converting-braket.md) for worked examples of each.
