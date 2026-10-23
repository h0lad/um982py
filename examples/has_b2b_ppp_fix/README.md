# Dual-service PPP fix with divergence telemetry

Collects PPP navigation and E6-HAS/B2b correction-delivery telemetry at a
static point and averages available positions with precision statistics.

## Run

After [installing the package](../README.md#running-the-examples), run these
commands from the `lib/um982py` directory.

Connect to a receiver:

```bash
python -m examples.has_b2b_ppp_fix --port /dev/ttyUSB0 --baud 921600 --augment \
    --ppp-service AUTO --duration 600 --debug --json /tmp/has-b2b-fix.json \
    --csv /tmp/has-b2b-epochs.csv
```

Replay a capture:

```bash
python -m examples.has_b2b_ppp_fix --replay captures/has-b2b.bin \
    --json /tmp/replay-fix.json
```

Run the cyclic example:

```bash
python -m examples.has_b2b_ppp_fix.cyclic --port /dev/ttyUSB0 --cycles 12 \
    --cycle-seconds 5 --debug --json /tmp/cyclic.json
```

`--augment` requests signal group 3/6 and PPP `AUTO`, the receiver's automatic
service selection. It may save a changed signal group. The `cyclic` example
subscribes to PPPNAV once and passes each pushed fix and its running mean to a
callback without polling the modem.

## Inputs and results

`--duration` controls the occupation, and `--csv` saves per-epoch results.
`--target-h-sigma`, `--target-v-sigma` and `--min-ppp` set precision and sample
criteria. The reported scatter and receiver sigmas are not independent accuracy
measurements.

## Understanding the result

Precise point positioning (PPP) uses satellite orbit, clock and bias
information to improve a position. This example collects PPP navigation and
correction-delivery telemetry during a stationary occupation and reports a
position estimate.

## References

Galileo HAS Signal-in-Space ICD; China Satellite Navigation Office
(2020), PPP-B2b ICD; Sanz Subirana et al. (2012), GNSS Data Processing.
