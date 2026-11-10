"""Pydantic v2 models for the oq-cal v0.1 calibration interchange format.

These models mirror ``spec/schema/oq-cal-0.1.schema.json``. Parse with
:meth:`OqCalDocument.model_validate_json` and serialise with
:meth:`OqCalDocument.model_dump_json`.

Only ``oq-cal``, ``device``, and ``snapshot`` are required.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class Unit(str, Enum):
    """SI-canonical units. Base SI only; no prefixes (converters normalise)."""

    SECOND = "s"
    HERTZ = "Hz"
    DIMENSIONLESS = "dimensionless"


class Status(str, Enum):
    """Per-datum calibration status, borrowed from the Boulder Opal snapshot vocabulary."""

    GOOD = "good"
    APPROXIMATE = "approximate"
    STALE = "stale"
    BAD = "bad"
    UNMEASURED = "unmeasured"


# ---------------------------------------------------------------------------
# Core datum
# ---------------------------------------------------------------------------


class _Model(BaseModel):
    """Base: permissive on extra keys so unknown source fields round-trip."""

    model_config = ConfigDict(
        extra="allow",
        use_enum_values=True,
        populate_by_name=True,
    )


class Datum(_Model):
    """A single measured value. ``value`` + ``unit`` are the only required fields.

    ``method`` names the protocol. ``metric`` names the quantity
    (``average_gate_fidelity``, ``readout_fidelity``, ``process_fidelity``, …).
    """

    value: float
    unit: Unit
    std_error: Optional[float] = Field(default=None, ge=0)
    err_minus: Optional[float] = Field(default=None, ge=0)
    err_plus: Optional[float] = Field(default=None, ge=0)
    median: Optional[float] = None
    method: Optional[str] = None
    metric: Optional[str] = None
    status: Optional[Status] = None
    updated_at: Optional[str] = None


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------


class Header(_Model):
    """The versioned schema header (``oq-cal`` section)."""

    model_config = ConfigDict(extra="forbid")

    name: Literal["oq-cal.device_calibration"] = "oq-cal.device_calibration"
    version: str = Field(pattern=r"^[0-9]+\.[0-9]+$")


class Device(_Model):
    """Which machine this document describes."""

    id: str
    vendor: Optional[str] = None
    model: Optional[str] = None
    num_qubits: Optional[int] = Field(default=None, ge=0)
    qubit_labels: Optional[dict[str, str]] = None
    enabled_qubits: Optional[list[str]] = None
    coupling_map: Optional[list[list[str]]] = None


class Snapshot(_Model):
    """When and from where the snapshot was captured."""

    id: Optional[str] = None
    captured_at: Optional[str] = None
    source: str
    source_schema: Optional[str] = None


# ---------------------------------------------------------------------------
# Readout / classifier / benchmark
# ---------------------------------------------------------------------------


class Classifier(_Model):
    """Readout discriminator parameters."""

    type: Optional[str] = None
    projection: Optional[list[float]] = None
    threshold: Optional[float] = None
    status: Optional[str] = None


class Readout(_Model):
    """Per-qubit readout characterization."""

    fidelity: Optional[Datum] = None
    duration: Optional[Datum] = None
    confusion_matrix: Optional[list[list[float]]] = None
    classifier: Optional[Classifier] = None


class Benchmark(_Model):
    """A protocol-level benchmark result (e.g. randomized benchmarking)."""

    protocol: str
    fidelity: Optional[Datum] = None
    error: Optional[Datum] = None
    qubits: Optional[list[str]] = None


# ---------------------------------------------------------------------------
# Per-qubit properties, gates, and aggregates
# ---------------------------------------------------------------------------


class QubitProperties(_Model):
    """Per-qubit characterization."""

    t1: Optional[Datum] = None
    t2: Optional[Datum] = None
    t2_echo: Optional[Datum] = None
    frequency_01: Optional[Datum] = None
    anharmonicity: Optional[Datum] = None
    readout: Optional[Readout] = None
    benchmarks: Optional[list[Benchmark]] = None


class _AggQubits(_Model):
    t1: Optional[Datum] = None
    t2: Optional[Datum] = None
    t2_echo: Optional[Datum] = None


class _AggReadout(_Model):
    fidelity: Optional[Datum] = None
    duration: Optional[Datum] = None


class _AggGate(_Model):
    fidelity: Optional[Datum] = None
    error: Optional[Datum] = None
    duration: Optional[Datum] = None


class Aggregates(_Model):
    """Device-level medians and averages."""

    qubits: Optional[_AggQubits] = None
    readout: Optional[_AggReadout] = None
    gates_1q: Optional[_AggGate] = None
    gates_2q: Optional[_AggGate] = None
    ops: Optional[dict[str, Datum]] = None


class GateEntry(_Model):
    """A characterized gate on specific qubits."""

    name: str
    qubits: list[str] = Field(min_length=1)
    fidelity: Optional[Datum] = None
    error: Optional[Datum] = None
    duration: Optional[Datum] = None
    benchmarks: Optional[list[Benchmark]] = None


class Defcal(_Model):
    """Per-gate pulse and control parameters, named after OpenQASM defcal."""

    gate: str
    qubits: list[str] = Field(min_length=1)
    params: Optional[dict[str, Any]] = None


# ---------------------------------------------------------------------------
# Document root
# ---------------------------------------------------------------------------


class OqCalDocument(_Model):
    """A complete oq-cal device calibration document."""

    oq_cal: Header = Field(alias="oq-cal")
    device: Device
    snapshot: Snapshot
    aggregates: Optional[Aggregates] = None
    qubits: Optional[dict[str, QubitProperties]] = None
    gates: Optional[list[GateEntry]] = None
    defcals: Optional[list[Defcal]] = None
    extensions: Optional[dict[str, Any]] = None

    def model_dump(self, *args, **kwargs):
        kwargs.setdefault("by_alias", True)
        return super().model_dump(*args, **kwargs)

    def model_dump_json(self, *args, **kwargs):
        kwargs.setdefault("by_alias", True)
        return super().model_dump_json(*args, **kwargs)
