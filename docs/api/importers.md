# Importers

The importers under `oq_cal.importers.*` convert vendor and tool formats into a
`OqCalDocument`. Each is registered under a short name (see
[`oq-cal formats`](../guides/cli.md#oq-cal-formats)) and applies the normalization rules
documented in the [converting guides](../guides/converting-braket.md).

## Braket: `oq_cal.importers.braket`

`from_braket` is the registered importer (`braket`). It reads
`braketSchemaHeader.name` and accepts standardized gate-model properties
(versions 1 and 3) and Rigetti device capabilities (version 2).

::: oq_cal.importers.braket.from_braket

::: oq_cal.importers.braket.from_braket_standardized

::: oq_cal.importers.braket.BraketSchemaError

## Rigetti capabilities: `oq_cal.importers.rigetti`

`from_braket` calls this when the header names Rigetti capabilities. It is not
registered on its own.

::: oq_cal.importers.rigetti.from_braket_rigetti

## IBM backend properties: `oq_cal.importers.ibm`

::: oq_cal.importers.ibm.from_ibm_properties

::: oq_cal.importers.ibm.IBMPropertiesError

## Boulder Opal: `oq_cal.importers.boulder_opal`

::: oq_cal.importers.boulder_opal.from_boulder_opal

## QUAM: `oq_cal.importers.quam`

::: oq_cal.importers.quam.from_quam_state

## Qiskit `Target`: `oq_cal.importers.qiskit`

::: oq_cal.importers.qiskit.from_qiskit_target
