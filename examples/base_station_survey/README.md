# Base station survey

Average repeated fixes until the base position meets the convergence criteria.
The survey skips differential and RTK positions with corrections older than
10 seconds.

## Run

Run from the repository root after [installation](../README.md#running-the-examples).

Connect to a receiver:

```bash
python -m examples.base_station_survey --port /dev/ttyUSB0 --baud 921600 \
    --json out.json
```

Replay the supplied capture:

```bash
python -m examples.base_station_survey \
    --replay tests/fixtures/captures/BESTXYZB.bin
```

The survey averages ECEF coordinates and derives ellipsoidal height. BESTNAV
`hgt` is height above mean sea level.

## Inputs and results

The survey uses BESTXYZ epochs and removes duplicates. Set the convergence
criteria with `--minimum-samples`, `--horizontal-tolerance` and
`--vertical-tolerance`. Use `--frames` and `--duration` to limit a live capture.
The JSON `status` stays `not_converged` until the criteria are met.

Convergence requires at least three distinct positions, and at least half of
the positions must be distinct. A clipped lag-one correlation adjusts the
standard error but does not fully account for long-memory correlation,
quantization or systematic errors.

## Understanding the result

Keep the antenna stationary during the survey. A stable average can still have
a systematic position error. ECEF coordinates are Earth-centred X/Y/Z in metres.
Geodetic height is above the reference ellipsoid. Before using the result for
an RTK base station, follow the [station survey guide](../ntrip_server/SURVEY.md)
and review an independent position solution.

## References

Unicore N4 R1.4 interface guide.
