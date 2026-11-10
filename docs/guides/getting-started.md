# Getting started

This guide converts a vendor payload into an oq-cal document, then validates and summarizes
it. The package name is `oq-cal` and the import path is `oq_cal`.

## Install

Clone the repository and install the Python library in editable mode. The reference
library lives under `python/`; run packaging commands from there.

```bash
git clone https://github.com/openquantum-oss/oq-cal-staging.git
cd oq-cal-staging/python

python -m venv .venv
source .venv/bin/activate

pip install -e ".[cli]"
pip install -e ".[qiskit]"
```

Verify the install:

```bash
oq-cal --version
oq-cal formats          # lists registered importers and exporters
```

```text
importers: boulder-opal, braket, ibm-properties, qiskit-target, quam-state
exporters: braket, qiskit
```

## Your first conversion

The repository ships a set of real public-device payloads under `fixtures/`. Convert
AWS Braket standardized device properties for IQM Garnet into an oq-cal document. Paths below
are relative to the repository root.

```bash
oq-cal convert fixtures/sources/braket/raw_iqm-garnet.json \
  --from braket --to oq-cal \
  -o garnet.oq-cal.json
```

`--from` selects an importer (or `oq-cal` to parse an oq-cal document directly); `--to` selects
an exporter (or `oq-cal` to emit canonical oq-cal JSON). With `--to oq-cal` you get the canonical
on-disk form, stable byte-for-byte; it is the form the conformance vectors are pinned to.

## Validate

```bash
oq-cal validate garnet.oq-cal.json
```

```text
OK: document is valid
```

`validate` runs both layers: JSON Schema plus the semantic checks (units, qubit bounds,
confusion-matrix sums, error-bar exclusivity). It exits `0` for a valid document and `1`
otherwise, so it drops straight into CI. See [Validating documents](validating.md).

## Summarize

```bash
oq-cal summary garnet.oq-cal.json
```

```text
device:   braket-device (? / ?)
qubits:   20
snapshot: aws-braket @ ?
sections: qubits(20), gates(30)
         T1: worst 2.361e-05 ($7)  best 5.198e-05 ($11)
         T2: worst 5.863e-06 ($13)  best 3.095e-05 ($19)
readout_fid: worst 0.9705 ($8)  best 0.9886 ($0)
gate_err: min 0.00144  max 0.0319  (n=30)
```

`summary` prints a compact device/calibration overview: which sections are populated and
the worst/best coherence, readout, and gate numbers. The `?` placeholders are fields the
Braket payload does not carry (vendor, model, and a capture timestamp).

## From Python

The same pipeline from Python, ending in a Qiskit transpiler `Target`:

```python
from oq_cal import OqCalDocument, validate
from oq_cal.exporters.qiskit import to_qiskit_target

doc = OqCalDocument.model_validate_json(open("garnet.oq-cal.json").read())
assert validate(doc) == []               # [] means valid

target = to_qiskit_target(doc)           # a transpiler-ready qiskit Target
print(target.num_qubits, list(target.operation_names))
```

## Next steps

- [Converting: AWS Braket](converting-braket.md): v1/v3 behaviors and normalization rules.
- [Qiskit integration](qiskit.md): `to_qiskit_target`, `broadcast_aggregates`, and the
  reverse import.
- [Diffing calibrations](diffing.md): drift reports between two snapshots.
- [CLI reference](cli.md): every command and flag.
