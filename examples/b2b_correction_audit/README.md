# Satellite correction and PPP-state audit

Audit PPP-B2b correction age and issue data alongside PPP epochs, and add `--has`
to capture Galileo E6-HAS. Use `--checks-csv` to export per-message B2b timing
and issue flags, and the JSON report includes a SHA-256 hash of any supplied
navigation reference. The [notebook](correction_timeline.ipynb) plots the
included B2b test capture.

## Run

After [installing the package](../README.md#running-the-examples), run these
commands from the `lib/um982py` directory.

Connect to a receiver:

```bash
python -m examples.b2b_correction_audit --port /dev/ttyUSB0 --baud 921600 \
    --duration 120 --has --alignment-window 60 --record /tmp/corrections.bin \
    --json /tmp/correction-audit.json
```

Replay the supplied capture:

```bash
python -m examples.b2b_correction_audit \
    --replay tests/fixtures/specialist/labelled-b2b.bin \
    --navigation tests/fixtures/specialist/navigation-issues.csv \
    --json /tmp/b2b-audit.json
```

Missing streams are reported as unobserved during the capture.

## Inputs and results

`--navigation` accepts an independent `slot,iodn` CSV for checking navigation
issues. `--max-age` and `--mask-max-age` set age limits in seconds, while
`--alignment-window` controls which earlier corrections appear beside a PPP
epoch.

## Understanding the result

BeiDou PPP-B2b and Galileo HAS are satellite-delivered
precise-point-positioning (PPP) correction services. This example reports
observed correction messages, their ages and issue identifiers alongside PPP
navigation records.

A message being received is evidence of delivery, not proof that the receiver
applied it or achieved a particular accuracy. A missing message in a short
capture only means it was not observed during that capture.

## References

China Satellite Navigation Office (2020), PPP-B2b ICD; Galileo HAS
Signal-in-Space Interface Control Document.
