# Paired dual-antenna reception study

Compare shared-epoch signals from both antenna inputs and report ANT1 − ANT2 C/N₀
by signal and 15° elevation bin, using one median per satellite. The
`--measurements-csv` option also exports pseudorange, raw carrier phase, Doppler
and lock-time comparisons. Phase differences retain unknown integer ambiguities
and are not calibrated baselines. Invalid phase and Doppler fields remain blank.
Use `--plot` to save C/N₀ differences when `matplotlib` is installed.

## Run

Run from the repository root after [installation](../README.md#running-the-examples).

Connect to a receiver:

```bash
python -m examples.dual_antenna_rf_audit --port /dev/ttyUSB0 --baud 921600 \
    --duration 300 --ant1-type helix --ant2-type patch --ant1-cable-m 2.0 \
    --ant2-cable-m 2.0 --record /tmp/dual-rf.bin \
    --pairs-csv /tmp/dual-pairs.csv --elevation-csv /tmp/dual-elevation.csv \
    --json /tmp/dual-rf.json
```

Replay a capture:

```bash
python -m examples.dual_antenna_rf_audit --replay /tmp/dual-rf.bin --antenna 2 \
    --json /tmp/dual-rf-ant2.json
```

## Inputs and results

The paired CSV contains observations from shared epochs. The elevation CSV
summarizes differences by signal and elevation bin. Antenna type and cable
length options record the setup.

## Understanding the result

Differences include the antennas, cables, receiver inputs and surroundings.
Swapping antennas helps separate some of those effects. This is not a
calibrated antenna-gain test.

## References

Unicore N4 R1.4 interface guide.

## Compare field captures

Run each capture with `--elevation-csv`, then compare signal and elevation-bin
summaries while recording field conditions:

```bash
python -m examples.dual_antenna_rf_audit.compare_passes --earlier snow.csv \
    --later water.csv --earlier-note 'snow cover' --later-note 'open water' \
    --output /tmp/repeat.json
```

Matching bins do not establish matched satellites, azimuths, antenna roles or
reflecting surfaces. Check those and the field conditions independently.
