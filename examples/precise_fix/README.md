# Static occupation and uncertainty

Estimate a stationary position from BESTXYZ epochs. The estimate excludes
gross outliers and differential or RTK positions with corrections older than
10 seconds.

## Run

Run from the repository root after [installation](../README.md#running-the-examples).

Connect to a receiver:

```bash
python -m examples.precise_fix --port /dev/ttyUSB0 --baud 921600 \
    --duration 300 --antenna-height 0.15 --json /tmp/fix.json \
    --csv /tmp/epochs.csv
```

Replay the supplied capture:

```bash
python -m examples.precise_fix --replay tests/fixtures/captures/BESTXYZB.bin \
    --json /tmp/replay-fix.json
```

Compare with a reference position:

```bash
python -m examples.precise_fix --port /dev/ttyUSB0 --reference-ecef X,Y,Z \
    --json /tmp/referenced-fix.json
```

## Inputs and results

Use `--csv` to save individual epochs and `--json` to save the estimate.
`--antenna-height 0.15` gives an example vertical offset in metres. With a
nonzero offset, the calculation treats the reported position as the antenna
phase centre and subtracts the offset to estimate the marker below it.

Measure the offset and check that this point definition matches the receiver
and antenna configuration. If the receiver already reports the marker position,
leave the offset at zero to avoid applying it twice. If you omit the option, it
defaults to zero and skips the marker estimate.

For a reviewed base-station survey, distinguish the antenna reference point
from the electrical phase centre as explained in the
[station survey guide](../ntrip_server/SURVEY.md#what---antenna-hen-h-e-n-means).

`--reference-ecef` takes comma-separated ECEF coordinates in metres, so replace
`X,Y,Z` with independently surveyed values before using that command.
The JSON `status` is `not_converged` until the sample and uncertainty criteria
are met.

## Understanding the result

For a stationary antenna, the report includes scatter and receiver uncertainty
estimates. Small scatter does not rule out systematic error.

## References

Unicore N4 R1.4 BESTXYZ position types and solution status.
