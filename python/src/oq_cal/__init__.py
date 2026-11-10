"""oq-cal: a vendor-neutral JSON interchange format for QPU calibration data.

Public surface:
    OqCalDocument           the document model
    validate               schema + semantic validation
    to_canonical_json      the canonical oq-cal JSON serialization
    register_importer/...  converter registry
"""

from __future__ import annotations

from .io import to_canonical_json
from .models import (
    Aggregates,
    Benchmark,
    Classifier,
    Datum,
    Defcal,
    Device,
    GateEntry,
    Header,
    OqCalDocument,
    QubitProperties,
    Readout,
    Snapshot,
    Status,
    Unit,
)
from .registry import (
    get_exporter,
    get_importer,
    list_formats,
    load_all,
    register_exporter,
    register_importer,
)
from .validate import ValidationIssue, validate

SPEC_VERSION = "0.1"
__version__ = "0.1.0"

__all__ = [
    "Aggregates",
    "Benchmark",
    "Classifier",
    "Datum",
    "Defcal",
    "Device",
    "GateEntry",
    "Header",
    "OqCalDocument",
    "QubitProperties",
    "Readout",
    "Snapshot",
    "Status",
    "Unit",
    "ValidationIssue",
    "validate",
    "to_canonical_json",
    "register_importer",
    "register_exporter",
    "get_importer",
    "get_exporter",
    "list_formats",
    "load_all",
    "SPEC_VERSION",
    "__version__",
]
