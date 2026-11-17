- Rigetti import no longer counts pulse-frame component ids toward `device.num_qubits`. Cepheus stays at 108.
- A pulse frame outside that roster is not emitted as a defcal.
- `oq-cal summary` counts a `0.5`/`1` sentinel as an unmeasured benchmark. A qubit is counted only when its coherence and readout are themselves placeholders.

Install the Python library with `pip install oq-cal`.
