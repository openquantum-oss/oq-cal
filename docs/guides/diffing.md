# Diffing calibrations

An oq-cal document is a snapshot of a device at a point in time. `oq-cal diff` compares two
snapshots **datum by datum** and reports the drift between them: which numbers moved, by
how much, and whether the move is significant. It is the tool for answering "has this device
degraded since yesterday?"

## The drift engine

`diff` flattens each document into a flat map of `path → value` over every datum-bearing
path, then compares the two maps. Each path produces one classified entry:

| Classification | Meaning |
|---|---|
| a datum **appeared** or **disappeared** | always `major` |
| value changed by more than `MAJOR_REL` | `major` |
| value changed by more than `MINOR_REL` | `minor` |
| smaller change | `noise` |

## Significance thresholds

Classification is by **relative** change, `|b - a| / |a|`:

| Tier | Threshold | Default |
|---|---|---|
| `major` | `|rel_change| > MAJOR_REL` | **0.20** (20%) |
| `minor` | `|rel_change| > MINOR_REL` | **0.05** (5%) |
| `noise` | otherwise | — |

Two edge cases:

- **Appearance / disappearance**: a datum present on one side only is always `major`
  (there is no relative change to compute).
- **Zero baseline**: when the baseline value is `0`, relative change is undefined; the
  entry is `major` if the absolute change is non-zero, otherwise `noise`.
- **Status, method, and metric**: a change to one of those strings produces a
  separate `major` entry at `<path>.status`, `<path>.method`, or `<path>.metric`,
  with `a_status` and `b_status` holding the old and new strings and no numeric
  change. A metric or method change is reported even when the number is the
  same, because the number then means a different quantity. `worst_offenders`
  ranks these after value changes. An unchanged string is not an entry.

## CLI: human-readable report

Compare two snapshots of the same device:

```bash
oq-cal diff garnet.oq-cal.json garnet_later.oq-cal.json
```

```text
drift: 1 major, 0 minor, 219 noise (220 total)
------------------------------------------------------------------------
[major] qubits.$0.t1: 2.61369e-05 -> 1.88186e-05  (-28.00%)
[noise] qubits.$0.readout.fidelity: 0.9886 -> 0.9801  (-0.86%)
```

The header counts entries by tier; each line shows the path, old and new values, and the
relative change. A T1 that fell 28% crosses the 20% `major` threshold; a readout fidelity
that slipped 0.86% is `noise`.

Comparing two *different* devices works too, and tends to produce many `major` entries from
appear/disappear as the qubit and pair topologies differ. That is useful for spotting
structural differences, less so for drift.

## JSON output

For dashboards and CI gates, `--json` emits a structured report:

```bash
oq-cal diff garnet.oq-cal.json garnet_later.oq-cal.json --json
```

```json
{
  "summary": {
    "counts": { "major": 1, "minor": 0, "noise": 219 },
    "total": 220,
    "worst_offenders": [
      { "path": "qubits.$0.t1",
        "a_value": 2.6136884458246837e-05,
        "b_value": 1.881855680993772e-05,
        "rel_change": -0.28,
        "significance": "major",
        "a_status": null,
        "b_status": null }
    ]
  },
  "entries": [ ... ]
}
```

`entries` lists every compared path with its old and new values, absolute and relative
change, and significance; `summary` condenses that into counts and the worst offenders.

`worst_offenders` is sorted by magnitude of relative change, with appear/disappear entries
(whose `rel_change` is `null`) sorted first. A status entry also has a null `rel_change`;
it is ranked after value changes so it does not crowd them out.

## From Python

```python
from oq_cal import OqCalDocument
from oq_cal.diff import diff

a = OqCalDocument.model_validate_json(open("garnet.oq-cal.json").read())
b = OqCalDocument.model_validate_json(open("garnet_later.oq-cal.json").read())

result = diff(a, b)
print(result.counts)                  # {"major": 1, "minor": 0, "noise": 219}
for e in result.worst_offenders(5):   # top 5 by relative change
    print(e.path, e.significance, e.rel_change)
```

!!! tip "Gate a CI job on drift"
    Because `diff --json` reports a `major` count, a nightly job can fail when a device
    drifts past the `major` threshold, an early-warning signal that a requalification is
    due.

See [Validating documents](validating.md) for checking each snapshot before comparing them,
and the [Python API](../api/diff.md) for the full `OqCalDiff` interface.
