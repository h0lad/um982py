# Hatch smoothing

Smooth code range with carrier-phase changes.

## Run

Run from the repository root after [installation](../README.md#running-the-examples).

Connect to a receiver:

```bash
python -m examples.hatch_smoothing --port /dev/ttyUSB0 --baud 921600 \
    --duration 120 --window 100 --record captures/hatch.bin --json hatch.json
```

Replay the supplied capture:

```bash
python -m examples.hatch_smoothing \
    --replay tests/fixtures/specialist/rtklib-motion.bin \
    --json /tmp/hatch.json
```

## Inputs and results

`--window` sets the smoothing window. Replay needs RANGE observations with
continuous carrier-phase arcs.

## Understanding the result

The filter implements the capped Hatch recursion
`P_k = P_k/k + (1 - 1/k)(P_{k-1} + L_k - L_{k-1})` on continuous phase arcs.
It resets when a cycle slip or gap breaks an arc. A single-frequency Hatch
filter is not divergence-free: the ionosphere delays code and advances carrier
phase, so a changing TEC biases the smoothed code over a long arc. The result
also retains the code and phase biases; it is not an independent accuracy
measurement.

## References

- Hatch (1982), *The synergism of GPS code and carrier measurements*,
  Geophysical Research Letters 9(4).
- [ESA Navipedia: Carrier-smoothing of code pseudoranges](https://gssc.esa.int/navipedia/index.php/Carrier-smoothing_of_code_pseudoranges).
- [ESA Navipedia: Code-carrier divergence effect](https://gssc.esa.int/navipedia/index.php/Code-Carrier_Divergence_Effect).
