# RTK outage and recovery campaign

Measures RTK fix loss and recovery against logged correction outages, excluding
unrecovered outages from recovery statistics.

## Run

After [installing the package](../README.md#running-the-examples), run these
commands from the `lib/um982py` directory.

Connect to a receiver:

```bash
python -m examples.rtk_outage_lab --port /dev/ttyUSB0 --baud 921600 \
    --duration 300 --outages link-events.csv --record /tmp/outage.bin \
    --truth-ecef X Y Z --timeline-csv /tmp/outage-timeline.csv \
    --json /tmp/recovery.json
```

Replay the supplied capture:

```bash
python -m examples.rtk_outage_lab \
    --replay tests/fixtures/specialist/labelled-outage.bin \
    --outages tests/fixtures/specialist/outages.csv --json /tmp/recovery.json
```

The `start,end` CSV uses absolute GPS seconds.

## Inputs and results

`--outages` reads a CSV with `start,end` in absolute GPS seconds.
`--truth-ecef` takes three independently known ECEF coordinates in metres, so
replace `X Y Z` in the live command or omit that option if no truth is
available.

## Understanding the result

This experiment compares receiver solution changes with a separately recorded
timeline of correction outages. RTK uses base observations and carrier phase
to improve the rover position, and recovery is the return of the observed fix
after an outage.

Outages with no observed recovery are censored rather than counted as successful
recoveries. Supply a truth position from an independent survey if you want to
compare positions against it.

## References

Unicore N4 R1.4; Kaplan & Hegarty (2017).
