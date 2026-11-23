# Cycle slip detection

Check for cycle slips by comparing phase changes with Doppler.

## Run

Run from the repository root after [installation](../README.md#running-the-examples).

Connect to a receiver:

```bash
python -m examples.cycle_slip_detection --port /dev/ttyUSB0 --baud 921600 \
    --duration 60 --record /tmp/cycle-slips.bin --json out.json
```

Replay that continuous capture:

```bash
python -m examples.cycle_slip_detection \
    --replay /tmp/cycle-slips.bin --max-gap 2
```

## Inputs and results

`--threshold` controls the Doppler-consistency test. `--frames` and `--interval`
control the sampled RANGE epochs.

`--max-gap` (default two seconds) bounds the interval over which endpoint
Doppler is integrated. Gaps and receiver lock-time resets start a new arc, and
duplicate or reversed epochs are rejected. `tested_increments` and
`unobserved_increments` distinguish the usable evidence from gaps. A single
epoch, including the supplied `RANGEB.bin` fixture, returns
`status: insufficient_data` and exit code 1.

A flag is a candidate discontinuity, not confirmation of an integer slip.
Dynamics, Doppler integration error and receiver clock events can also cause
flags. Zero flags says nothing about unobserved intervals. The CLI tests GPS
L1 C/A, while the Python geometry-free helper also splits gaps and frequency
changes.

## References

Blewitt (1990), GPS cycle-slip editing.

[ESA Navipedia: carrier-phase cycle-slip detection](https://gssc.esa.int/navipedia/index.php/Carrier_Phase_Cycle-Slip_Detection).
