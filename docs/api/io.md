# Serialization

`oq_cal.io` defines the **canonical JSON form**: the on-disk representation the
[conformance vectors](../conformance.md) are pinned to. The Python writer is
deterministic. Another language proves conformance by structural equality. Python
and JavaScript may print the same number differently (`5120` and `5120.0`).

::: oq_cal.io
