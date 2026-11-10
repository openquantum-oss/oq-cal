"""oq_cal importers. Converter modules self-register on import.

Importing this package triggers each converter module's
``register_importer(...)`` side effect. Modules with a missing optional
dependency import tolerantly (the registry's ``load_all`` also guards this).
"""

from __future__ import annotations

from . import boulder_opal, braket, ibm, quam, rigetti  # noqa: F401  (self-registration)

try:  # qiskit is an optional dependency of the importer surface
    from . import qiskit  # noqa: F401
except Exception:  # pragma: no cover - only when qiskit is absent
    pass
