"""Importer / exporter registry for oq-cal converters.

Converter modules self-register on import. An importer maps a source ``dict``
to a :class:`~oq_cal.models.OqCalDocument`; an exporter maps a ``OqCalDocument`` to
any target object. Modules under ``oq_cal.importers`` and ``oq_cal.exporters``
call :func:`register_importer` / :func:`register_exporter` at import time.
:func:`load_all` imports those packages so registration happens as a side effect.
"""

from __future__ import annotations

import importlib
import pkgutil
from typing import Any, Callable

from .models import OqCalDocument

Importer = Callable[[dict], OqCalDocument]
Exporter = Callable[[OqCalDocument], Any]

_IMPORTERS: dict[str, Importer] = {}
_EXPORTERS: dict[str, Exporter] = {}


def register_importer(name: str, fn: Importer) -> Importer:
    """Register an importer under ``name``. Usable as a decorator."""
    _IMPORTERS[name] = fn
    return fn


def register_exporter(name: str, fn: Exporter) -> Exporter:
    """Register an exporter under ``name``. Usable as a decorator."""
    _EXPORTERS[name] = fn
    return fn


def get_importer(name: str) -> Importer:
    """Return the importer registered under ``name`` (raises KeyError if absent)."""
    load_all()
    return _IMPORTERS[name]


def get_exporter(name: str) -> Exporter:
    """Return the exporter registered under ``name`` (raises KeyError if absent)."""
    load_all()
    return _EXPORTERS[name]


def list_formats() -> dict[str, list[str]]:
    """Return the names of all registered importers and exporters."""
    load_all()
    return {
        "importers": sorted(_IMPORTERS),
        "exporters": sorted(_EXPORTERS),
    }


_loaded = False


def load_all() -> None:
    """Import every submodule of ``oq_cal.importers`` and ``oq_cal.exporters``.

    Tolerant by design: a converter whose optional dependency is missing (e.g.
    the Qiskit exporter without qiskit installed) is skipped rather than fatal.
    """
    global _loaded
    if _loaded:
        return
    _loaded = True
    for pkg_name in ("oq_cal.importers", "oq_cal.exporters"):
        try:
            pkg = importlib.import_module(pkg_name)
        except ModuleNotFoundError:
            continue
        for mod in pkgutil.iter_modules(pkg.__path__):
            if mod.name.startswith("_"):
                continue
            try:
                importlib.import_module(f"{pkg_name}.{mod.name}")
            except Exception:
                # A converter with a missing optional dependency must not break
                # discovery of the others.
                continue
