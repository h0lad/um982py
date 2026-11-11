# RTK outage and recovery campaign

Measure RTK fix loss and recovery during logged correction outages. Recovery
statistics exclude outages with no observed recovery.

## Run

Run from the repository root after [installation](../README.md#running-the-examples).

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

## Inputs and results

`--outages` reads a CSV with `start,end` in absolute GPS seconds.
`--truth-ecef` takes three independently known ECEF coordinates in metres, so
replace `X Y Z` in the live command or omit that option if no truth is
available.

## Understanding the result

The timeline distinguishes the raw fixed class from a fresh fixed state. A
fresh fixed state requires a computed fixed solution with corrections aged 0 to
10 seconds. Recovery means an observed loss followed by a sustained fresh fix.
A fresh fix that continues through an outage counts as retained. Gaps or
missing observations before the outage prevent a retention result.

## References

- Unicore N4 R1.4.
- Kaplan & Hegarty (2017).
