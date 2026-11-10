"""Tests for the importer/exporter registry scaffold."""

from __future__ import annotations

from oq_cal import list_formats, register_exporter, register_importer
from oq_cal.registry import get_exporter, get_importer


def test_register_and_retrieve(tmp_path):
    def imp(d):  # pragma: no cover - trivial
        return d

    def exp(doc):  # pragma: no cover - trivial
        return doc

    register_importer("_test_imp", imp)
    register_exporter("_test_exp", exp)

    assert get_importer("_test_imp") is imp
    assert get_exporter("_test_exp") is exp
    fmts = list_formats()
    assert "_test_imp" in fmts["importers"]
    assert "_test_exp" in fmts["exporters"]


def test_load_all_tolerant():
    # No converters shipped yet; load_all must not raise and lists stay structured.
    fmts = list_formats()
    assert set(fmts) == {"importers", "exporters"}
