"""oq_cal exporters. Converter modules self-register on import.

Importing this package imports each exporter module so its
``register_exporter(...)`` call runs as a side effect. Modules whose optional
dependency is unavailable are skipped tolerantly (the Braket exporter has no
third-party dependency; the Qiskit exporter requires ``qiskit``).
"""

from __future__ import annotations

from . import braket as braket  # noqa: F401

try:  # qiskit is an optional dependency
    from . import qiskit as qiskit  # noqa: F401
except ModuleNotFoundError:  # pragma: no cover - exercised only without qiskit
    pass
