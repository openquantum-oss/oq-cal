"""Fidelity-to-error rule, independent of Qiskit."""

import pytest

from oq_cal.exporters._error import error_from_fidelity


def test_average_gate_fidelity_converts_quietly():
    error, warning = error_from_fidelity(0.999, "average_gate_fidelity")
    assert error == pytest.approx(0.001)
    assert warning is None


def test_readout_fidelity_converts_quietly():
    error, warning = error_from_fidelity(0.98, "readout_fidelity")
    assert error == pytest.approx(0.02)
    assert warning is None


def test_absent_metric_converts_and_warns():
    error, warning = error_from_fidelity(0.9, None)
    assert error == pytest.approx(0.1)
    assert warning is not None
    assert "absent" in warning


def test_process_fidelity_and_rb_decay_are_not_converted():
    for metric in ("process_fidelity", "state_fidelity", "rb_decay", "assignment_error"):
        error, warning = error_from_fidelity(0.9, metric)
        assert error is None
        assert metric in warning
