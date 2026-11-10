"""Export an oq-cal document to a Qiskit :class:`~qiskit.transpiler.Target`.

Projects SI-canonical calibration data onto Qiskit's in-memory ``Target``.

Design choices
--------------
* **Warnings.** Mapping is best-effort and never raises on sparse or partially
  unmappable documents. Anything that cannot be mapped (unknown gate names,
  parameterised gates with no known arity, etc.) is reported as a warning. By
  default warnings are emitted on the module logger
  (``logging.getLogger("oq_cal.exporters.qiskit")``). Callers that want to collect
  them programmatically may pass ``on_warning=callable``; it receives one string
  per warning and suppresses the log emission.
* **Missing qubit count.** A Qiskit ``Target`` requires a qubit count. If the
  document's ``device.num_qubits`` is absent (allowed by spec §4, e.g. an
  aggregates-only trapped-ion payload), :func:`to_qiskit_target` raises a
  ``ValueError`` naming the problem rather than guessing a count.
* **Errors.** A gate's error is taken from its ``error`` datum when present.
  ``1 - fidelity`` is used only when ``metric`` is ``average_gate_fidelity`` or
  ``readout_fidelity``, or when ``metric`` is absent. An absent metric is an
  assumption: the exporter warns and still applies ``1 - fidelity`` so a
  document written before the field still yields a transpiler error. Any other
  metric (``process_fidelity``, ``rb_decay``, …) is not converted.
* **Benchmarks.** Qubit and gate benchmarks become instructions named by
  ``protocol``. They are not copied onto ``x`` or any other physical gate.
  The same error rule applies. A protocol that collides with an instruction
  already on the target is skipped.
* **Broadcasting aggregates.** Aggregates-only documents carry no per-qubit or
  per-gate granularity. With ``broadcast_aggregates=True`` the device-level 1q
  duration/error is applied to a standard single-qubit instruction set on every
  qubit, and the 2q duration/error to a two-qubit instruction over every pair in
  ``device.coupling_map`` (or, absent a coupling map, every ordered distinct
  pair, the all-to-all assumption). Default is ``False``: aggregates alone
  produce a ``Target`` with qubit count only.
"""

from __future__ import annotations

import logging
from typing import Callable, Optional

from qiskit.circuit import Instruction, Measure, Parameter
from qiskit.circuit.library import (
    CCXGate,
    CXGate,
    CZGate,
    HGate,
    RXGate,
    RYGate,
    RZGate,
    SGate,
    SXGate,
    SwapGate,
    XGate,
    YGate,
    ZGate,
)
from qiskit.transpiler import InstructionProperties, QubitProperties, Target

from ..models import OqCalDocument
from ..registry import register_exporter
from ._error import error_from_fidelity

_logger = logging.getLogger("oq_cal.exporters.qiskit")

# stdgates name -> factory producing a fresh qiskit gate instance.
# Parameterised rotations get a free Parameter so the Target records the shape.
_GATE_FACTORIES: dict[str, Callable[[], object]] = {
    "x": XGate,
    "y": YGate,
    "z": ZGate,
    "h": HGate,
    "s": SGate,
    "sx": SXGate,
    "cx": CXGate,
    "cnot": CXGate,
    "cz": CZGate,
    "swap": SwapGate,
    "ccx": CCXGate,
    "rx": lambda: RXGate(Parameter("theta")),
    "ry": lambda: RYGate(Parameter("theta")),
    "rz": lambda: RZGate(Parameter("theta")),
}


def _qubit_index(ref: str) -> Optional[int]:
    """Parse a ``$n`` physical-qubit reference into an int, or ``None``."""
    if isinstance(ref, str) and ref.startswith("$") and ref[1:].isdigit():
        return int(ref[1:])
    return None


def _datum_value(datum) -> Optional[float]:
    if datum is None:
        return None
    return getattr(datum, "value", None)


# Datum statuses whose placeholder value MUST NOT be treated as a measurement
# (spec §2): a dead / uncalibrated element produces no instruction entry rather
# than one carrying its sentinel value.
_DEAD_STATUSES = frozenset({"bad", "unmeasured"})


def _is_dead(datum) -> bool:
    return datum is not None and getattr(datum, "status", None) in _DEAD_STATUSES


def _gate_error(entry_error, entry_fidelity, warn, where: str) -> Optional[float]:
    """Resolve an error value. An explicit error wins. Otherwise see spec §2."""
    if entry_error is not None and not _is_dead(entry_error):
        err = _datum_value(entry_error)
        if err is not None:
            return err
    if entry_fidelity is None or _is_dead(entry_fidelity):
        return None
    derived, warning = error_from_fidelity(
        _datum_value(entry_fidelity), getattr(entry_fidelity, "metric", None)
    )
    if warning:
        warn(f"{where}: {warning}")
    return derived


def _qargs(refs) -> Optional[tuple]:
    parsed = tuple(_qubit_index(q) for q in refs)
    if any(q is None for q in parsed):
        return None
    return parsed


def _benchmark_error(benchmark, warn) -> tuple[Optional[float], bool]:
    """Return ``(error, skip)``. ``skip`` means the benchmark is not projected."""
    protocol = getattr(benchmark, "protocol", None) or "benchmark"
    if _is_dead(getattr(benchmark, "error", None)) or _is_dead(
        getattr(benchmark, "fidelity", None)
    ):
        warn(f"benchmark {protocol!r} is bad/unmeasured; skipped")
        return None, True
    explicit = _datum_value(getattr(benchmark, "error", None))
    if explicit is not None:
        return explicit, False
    fidelity = getattr(benchmark, "fidelity", None)
    derived, warning = error_from_fidelity(
        _datum_value(fidelity), getattr(fidelity, "metric", None) if fidelity else None
    )
    if warning:
        warn(f"benchmark {protocol!r}: {warning}")
    if derived is None and fidelity is None:
        return None, True
    return derived, False


def _project_benchmarks(doc: OqCalDocument, target, warn) -> None:
    """Project protocol benchmarks onto instructions named by the protocol.

    A Qiskit ``Target`` has no benchmark slot. The protocol name (``rb``,
    ``simultaneous_rb``, …) is the instruction name, on the benchmark's qubits.
    The result is not attached to ``x`` or any other physical gate.
    """
    pending: list[tuple[str, tuple, Optional[float]]] = []

    def take(benchmark, qargs: Optional[tuple]) -> None:
        protocol = getattr(benchmark, "protocol", None)
        if not isinstance(protocol, str) or not protocol:
            warn("benchmark is missing a protocol; skipped")
            return
        if not qargs:
            warn(f"benchmark {protocol!r} has no qubit refs; skipped")
            return
        err, skip = _benchmark_error(benchmark, warn)
        if skip:
            return
        pending.append((protocol, qargs, err))

    if doc.qubits:
        for ref, props in doc.qubits.items():
            parent = _qargs([ref])
            for benchmark in props.benchmarks or []:
                qargs = _qargs(list(benchmark.qubits)) if benchmark.qubits else parent
                take(benchmark, qargs)
    for entry in doc.gates or []:
        parent = _qargs(list(entry.qubits))
        for benchmark in entry.benchmarks or []:
            qargs = _qargs(list(benchmark.qubits)) if benchmark.qubits else parent
            take(benchmark, qargs)

    by_protocol: dict[str, list[tuple[tuple, Optional[float]]]] = {}
    for protocol, qargs, err in pending:
        by_protocol.setdefault(protocol, []).append((qargs, err))

    existing = set(target.operation_names)
    for protocol, items in by_protocol.items():
        arities = {len(q) for q, _err in items}
        named: dict[str, list[tuple[tuple, Optional[float]]]] = {}
        if len(arities) == 1:
            named[protocol] = items
        else:
            warn(
                f"benchmark {protocol!r} spans qubit counts {sorted(arities)}; "
                "splitting into one instruction per count"
            )
            for n in sorted(arities):
                named[f"{protocol}_{n}q"] = [(q, e) for q, e in items if len(q) == n]
        for name, group in named.items():
            if name in existing:
                warn(f"benchmark {protocol!r} collides with instruction {name!r}; skipped")
                continue
            width = len(group[0][0])
            instruction = Instruction(name=name, num_qubits=width, num_clbits=0, params=[])
            qmap = {
                qargs: InstructionProperties(duration=None, error=err) for qargs, err in group
            }
            target.add_instruction(instruction, qmap, name=name)
            existing.add(name)


def to_qiskit_target(
    doc: OqCalDocument,
    *,
    broadcast_aggregates: bool = False,
    on_warning: Optional[Callable[[str], None]] = None,
) -> Target:
    """Project an oq-cal document onto a Qiskit :class:`Target`.

    Parameters
    ----------
    doc:
        The source calibration document.
    broadcast_aggregates:
        When ``True`` and the document carries ``aggregates``, broadcast the
        device-level 1q/2q duration+error onto per-qubit / per-pair
        instructions. See the module docstring for the exact behaviour.
    on_warning:
        Optional callback receiving one warning string per unmappable item. When
        provided, warnings are not also logged.

    Returns
    -------
    Target
        A transpiler target populated with whatever the document expresses.
        Never raises on sparse / partially unmappable input.
    """

    def warn(msg: str) -> None:
        if on_warning is not None:
            on_warning(msg)
        else:
            _logger.warning(msg)

    num_qubits = doc.device.num_qubits
    if num_qubits is None:
        raise ValueError(
            "cannot build a Qiskit Target: device.num_qubits is absent. A Target "
            "requires a qubit count, but this oq-cal document does not publish one "
            "(e.g. an aggregates-only trapped-ion payload). Supply the count on the "
            "document's device.num_qubits before exporting."
        )

    # --- Qubit properties ---------------------------------------------------
    qubit_props: Optional[list[QubitProperties]] = None
    if doc.qubits:
        qubit_props = []
        for i in range(num_qubits):
            props = doc.qubits.get(f"${i}")
            if props is None:
                qubit_props.append(QubitProperties())
                continue
            qubit_props.append(
                QubitProperties(
                    t1=_datum_value(props.t1),
                    t2=_datum_value(props.t2),
                    frequency=_datum_value(props.frequency_01),
                )
            )

    target = Target(num_qubits=num_qubits, qubit_properties=qubit_props)

    # --- Per-gate instructions ---------------------------------------------
    # Group gate entries by stdgates name so a single qiskit instruction carries
    # a {qargs: InstructionProperties} map across all qubits it acts on.
    by_name: dict[str, dict[tuple, InstructionProperties]] = {}
    for entry in doc.gates or []:
        # A dead edge (status bad/unmeasured on its error/fidelity datum) carries
        # a placeholder value, not a measurement: produce no instruction entry.
        if _is_dead(entry.error) or _is_dead(entry.fidelity):
            warn(f"gate {entry.name!r} on {entry.qubits} is bad/unmeasured; skipped")
            continue
        factory = _GATE_FACTORIES.get(entry.name)
        if factory is None:
            warn(f"gate {entry.name!r} on {entry.qubits} has no qiskit class; skipped")
            continue
        qargs = tuple(_qubit_index(q) for q in entry.qubits)
        if any(q is None for q in qargs):
            warn(f"gate {entry.name!r} has malformed qubit refs {entry.qubits}; skipped")
            continue
        err = _gate_error(
            entry.error, entry.fidelity, warn, f"gate {entry.name!r} on {entry.qubits}"
        )
        dur = _datum_value(entry.duration)
        props = InstructionProperties(duration=dur, error=err)
        by_name.setdefault(entry.name, {})[qargs] = props

    for name, qargs_map in by_name.items():
        target.add_instruction(_GATE_FACTORIES[name](), qargs_map, name=name)

    # --- Measurement from per-qubit readout --------------------------------
    measure_map: dict[tuple, InstructionProperties] = {}
    if doc.qubits:
        for i in range(num_qubits):
            props = doc.qubits.get(f"${i}")
            if props is None or props.readout is None:
                continue
            # A dead readout (status bad/unmeasured) carries a placeholder
            # fidelity, not a measurement: produce no readout error entry.
            if _is_dead(props.readout.fidelity):
                warn(f"readout on $%d is bad/unmeasured; skipped" % i)
                continue
            dur = _datum_value(props.readout.duration)
            err = _gate_error(
                None, props.readout.fidelity, warn, f"readout on ${i}"
            )
            if err is None and dur is None:
                continue
            measure_map[(i,)] = InstructionProperties(duration=dur, error=err)
    if measure_map:
        target.add_instruction(Measure(), measure_map, name="measure")

    # --- Aggregate broadcasting --------------------------------------------
    if broadcast_aggregates and doc.aggregates is not None:
        _broadcast_aggregates(doc, target, by_name, warn)

    _project_benchmarks(doc, target, warn)
    return target


# Standard broadcast instruction sets.
_BROADCAST_1Q = ("x", "sx", "rz")
_BROADCAST_2Q = "cz"


def _broadcast_aggregates(doc, target, existing_by_name, warn) -> None:
    num_qubits = doc.device.num_qubits
    agg = doc.aggregates

    # 1q broadcast.
    if agg.gates_1q is not None:
        dur = _datum_value(agg.gates_1q.duration)
        err = _gate_error(
            agg.gates_1q.error, agg.gates_1q.fidelity, warn, "aggregates.gates_1q"
        )
        for name in _BROADCAST_1Q:
            if name in existing_by_name:
                continue
            props = {
                (q,): InstructionProperties(duration=dur, error=err)
                for q in range(num_qubits)
            }
            if props:
                target.add_instruction(_GATE_FACTORIES[name](), props, name=name)

    # 2q broadcast over coupling map, or all-to-all if none.
    if agg.gates_2q is not None and _BROADCAST_2Q not in existing_by_name:
        dur = _datum_value(agg.gates_2q.duration)
        err = _gate_error(
            agg.gates_2q.error, agg.gates_2q.fidelity, warn, "aggregates.gates_2q"
        )
        pairs: list[tuple[int, int]] = []
        if doc.device.coupling_map:
            for pair in doc.device.coupling_map:
                idx = tuple(_qubit_index(q) for q in pair)
                if len(idx) == 2 and all(q is not None for q in idx):
                    pairs.append(idx)  # type: ignore[arg-type]
        else:
            warn(
                "broadcast_aggregates: no coupling_map; assuming all-to-all 2q "
                "connectivity for aggregate 2q broadcast"
            )
            pairs = [
                (a, b)
                for a in range(num_qubits)
                for b in range(num_qubits)
                if a != b
            ]
        if pairs:
            props = {
                pair: InstructionProperties(duration=dur, error=err) for pair in pairs
            }
            target.add_instruction(_GATE_FACTORIES[_BROADCAST_2Q](), props, name=_BROADCAST_2Q)


register_exporter("qiskit", to_qiskit_target)
