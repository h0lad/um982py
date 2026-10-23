# Broadcast orbit audit

Compare GPS broadcast orbits with a precise SP3 product and export radial,
along-track and cross-track differences with `--differences-csv`. The optional
`--plot` argument saves a figure when `matplotlib` is installed. The
[notebook](orbit_comparison.ipynb) plots the radial component using the included
RTKLIB fixture.

## Run

After [installing the package](../README.md#running-the-examples), run these
commands from the `lib/um982py` directory.

Connect to a receiver:

```bash
python -m examples.broadcast_orbit_audit --port /dev/ttyUSB0 --baud 921600 \
    --duration 60 --record captures/ephemerides.bin \
    --sp3 products/reference.sp3 --json orbit-audit.json
```

Replay a capture:

```bash
python -m examples.broadcast_orbit_audit --replay captures/ephemerides.bin \
    --sp3 products/reference.sp3 --json orbit-audit.json
```

## Inputs and results

Provide a matching SP3-c or SP3-d product with `--sp3`, which must explicitly use
GPS time. Predicted orbit epochs are excluded unless `--include-predicted` is
set.

## Understanding the result

The example propagates broadcast ephemerides and compares the resulting
positions with the satellite positions in the supplied SP3 product. The product
must cover the satellites and epochs being compared. The differences measure
agreement with that product, not the rover's position accuracy.

The supplied `GPSEPHA.bin` fixture contains a G17 ephemeris that differs from
the corresponding IGS broadcast data and produces a large orbit discrepancy.

## References

Hilla (2010), SP3-c; IS-GPS-200.
