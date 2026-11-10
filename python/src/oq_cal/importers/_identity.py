"""Shared convert-time device identity and provenance handling for importers.

Every importer accepts the same optional keyword arguments so a caller (or the
``oq-cal convert`` CLI) can stamp a converted document with the identity and
capture provenance that the source payload does not carry. A supplied value
ALWAYS overrides whatever the importer would otherwise derive from the source;
an omitted value leaves the source-derived (or absent) behavior untouched.

The five fields are:

* ``device_id`` -> ``device.id``
* ``vendor``    -> ``device.vendor``
* ``model``     -> ``device.model``
* ``captured_at`` -> ``snapshot.captured_at``
* ``snapshot_id`` -> ``snapshot.id``
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ..models import Device, Snapshot


@dataclass(frozen=True)
class Identity:
    """Caller-supplied identity/provenance overrides (all optional)."""

    device_id: Optional[str] = None
    vendor: Optional[str] = None
    model: Optional[str] = None
    captured_at: Optional[str] = None
    snapshot_id: Optional[str] = None


def apply_identity(device: Device, snapshot: Snapshot, identity: Identity) -> None:
    """Apply any supplied identity overrides onto ``device`` and ``snapshot``.

    Only non-``None`` fields are applied, so each override wins over whatever the
    importer already set and omitted fields leave the current behavior intact.
    """
    if identity.device_id is not None:
        device.id = identity.device_id
    if identity.vendor is not None:
        device.vendor = identity.vendor
    if identity.model is not None:
        device.model = identity.model
    if identity.captured_at is not None:
        snapshot.captured_at = identity.captured_at
    if identity.snapshot_id is not None:
        snapshot.id = identity.snapshot_id
