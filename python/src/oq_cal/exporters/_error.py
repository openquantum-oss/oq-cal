"""Decide when a fidelity number may be turned into an error rate.

This module stays free of the optional Qiskit dependency so the rule can be
tested without Qiskit installed. Spec §2: ``1 - fidelity`` is an error only
when ``metric`` is ``average_gate_fidelity`` or ``readout_fidelity``.
"""

from __future__ import annotations

from typing import Optional

# Quantities for which the error rate is 1 - value.
_FIDELITY_AS_ERROR = frozenset({"average_gate_fidelity", "readout_fidelity"})


def error_from_fidelity(
    fidelity: Optional[float], metric: Optional[str]
) -> tuple[Optional[float], Optional[str]]:
    """Return ``(error, warning)``.

    ``warning`` is set when the conversion is an assumption (``metric`` absent)
    or when it is refused. An explicit error datum is the caller's job and is
    not passed here.
    """
    if fidelity is None:
        return None, None
    if metric in _FIDELITY_AS_ERROR:
        return 1.0 - fidelity, None
    if metric is None:
        return 1.0 - fidelity, (
            "fidelity metric is absent; assuming error = 1 - fidelity"
        )
    return None, (
        f"fidelity metric {metric!r} is not an average-gate or readout fidelity; "
        "not converting 1 - fidelity to an error"
    )
