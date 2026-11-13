# Satellite correction and PPP-state audit

Audit PPP-B2b correction age and issue data alongside PPP epochs. Add `--has` to
capture Galileo E6-HAS. Use `--checks-csv` to export timing and issue flags for
each B2b message. The JSON report includes a SHA-256 hash of any supplied
navigation reference. The [notebook](correction_timeline.ipynb) plots the
included B2b test capture.

## Run

Run from the repository root after [installation](../README.md#running-the-examples).

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

The report marks missing streams as unobserved.
The replay's type-4 clock block also reports `satellite_mapping_unverified`:
its satellite mapping has not been independently established.

## Inputs and results

`--navigation` accepts an independent `slot,iodn` CSV for checking navigation
issues. `--max-age` and `--mask-max-age` set age limits in seconds, while
`--alignment-window` controls which earlier corrections appear beside a PPP
epoch.

## References

- China Satellite Navigation Office (2020), PPP-B2b ICD.
- Galileo HAS Signal-in-Space Interface Control Document.
