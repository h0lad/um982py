# Paired dual-antenna reception study

Compare shared-epoch signals from both antenna inputs and report ANT1 − ANT2 C/N₀
by signal and 15° elevation bin, using one median per satellite. The
`--measurements-csv` option also exports pseudorange, raw carrier phase, Doppler
and lock-time comparisons. Phase differences retain unknown integer ambiguities
and are not calibrated baselines. Invalid phase and Doppler fields remain blank.
Use `--plot` to save C/N₀ differences when `matplotlib` is installed.

## Run

After [installing the package](../README.md#running-the-examples), run these
commands from the `lib/um982py` directory.

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

Results include cable and site effects, so swap antennas to compare contributions.

## Inputs and results

The paired CSV contains shared-epoch observations, and the elevation CSV
summarizes differences by signal and elevation bin. Antenna type and cable
length options record the setup. The measurements also reflect the receiver
inputs and local environment.

## Understanding the result

This compares signal strength reported for the same satellites and signals at
the two antenna inputs. C/N₀ is the receiver's carrier-to-noise-density
estimate, and the output groups paired differences by signal and elevation.

Differences include antennas, cables, receiver inputs and surroundings.
Swapping the antennas and repeating the measurement helps separate some of
those effects, but the report is not a calibrated antenna-gain test.

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
