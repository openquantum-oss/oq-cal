"""Canonical oq-cal JSON serialization.

This module is the reference writer. The CLI and the conformance generator
call it. The form is:

* **2-space indent**;
* **exclude-None**: optional model fields whose value is ``None`` are omitted,
  so an absent section never appears as ``null``. JSON ``null`` inside
  ``extensions`` is kept, because that section is a verbatim payload;
* **model field order**: keys follow the declaration order of the pydantic
  models, not sorted keys;
* **UTF-8**, with non-ASCII characters emitted verbatim (not ``\\uXXXX``-escaped);
* a single **trailing newline**.

The string comes from :meth:`pydantic.BaseModel.model_dump_json`
(``indent=2, exclude_none=True``) plus a trailing newline. pydantic's JSON
encoder owns how datum values, enums, and nested models serialize.
"""

from __future__ import annotations

from .models import OqCalDocument


def to_canonical_json(doc: OqCalDocument) -> str:
    """Serialize *doc* to the canonical oq-cal JSON string (with trailing newline).

    See the module docstring for the normative definition of the canonical form.
    """
    return doc.model_dump_json(indent=2, exclude_none=True) + "\n"
