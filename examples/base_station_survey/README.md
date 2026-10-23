# Base station survey

Averages repeated fixes until a base-station position converges.
Differential and RTK positions with corrections older than 10 seconds are skipped.

## Run

After [installing the package](../README.md#running-the-examples), run these
commands from the `lib/um982py` directory.

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

The survey mean is ECEF (ellipsoidal height), while BESTNAV `hgt` is MSL height.

## Inputs and results

The survey uses BESTXYZ epochs. Use `--minimum-samples`,
`--horizontal-tolerance` and `--vertical-tolerance` to set the convergence
criteria, while `--frames` and `--duration` bound a live collection.
The JSON `status` is `not_converged` until the criteria are met.

## Understanding the result

This example averages repeated positions while the antenna remains stationary
and reports the variation and a convergence check. ECEF means Earth-centred
X/Y/Z coordinates in metres, and the reported geodetic height is above the
reference ellipsoid.

A stable average can still have a systematic position error. For a base
station intended to provide RTK observations, follow the longer [station
survey guide](../ntrip_server/SURVEY.md) and review an independent position
solution before using it as a surveyed base.

## References

Unicore N4 R1.4 interface guide.
