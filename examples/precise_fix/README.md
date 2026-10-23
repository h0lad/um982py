# Static occupation and uncertainty

Estimates a static position from BESTXYZ epochs, rejecting gross outliers.
The estimate excludes differential and RTK positions with corrections older
than 10 seconds. Receiver scatter alone cannot measure accuracy.

## Run

After [installing the package](../README.md#running-the-examples), run these
commands from the `lib/um982py` directory.

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

`--csv` saves individual epochs and `--json` saves the estimate.
`--antenna-height 0.15` is an **example**, in metres. When nonzero, the code
treats the reported position as the antenna phase-centre position and subtracts
that vertical height to estimate a marker below it. Use a measured value only
when that point definition matches your receiver and antenna configuration, and
do not apply the offset again if the position has already been reduced to the
marker. Omit the option to use its zero default and skip the marker estimate.
For a reviewed base-station survey, distinguish the antenna reference point
from the electrical phase centre as explained in the
[station survey guide](../ntrip_server/SURVEY.md#what---antenna-hen-h-e-n-means).
`--reference-ecef` takes comma-separated ECEF coordinates in metres, so replace
`X,Y,Z` with independently surveyed values before using that command.
The JSON `status` is `not_converged` until the sample and uncertainty criteria
are met.

## Understanding the result

For a stationary antenna, the example averages receiver position epochs,
screens gross outliers and reports scatter and receiver uncertainty estimates.
Small scatter can coexist with systematic error, so compare against an
independently known Earth-centred position in a compatible reference frame and
epoch. A short occupation does not automatically yield a surveyed base
coordinate.

## References

Unicore N4 R1.4 BESTXYZ position types and solution status.
