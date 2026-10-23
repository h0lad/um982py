# Position tracking

Collects position fixes with precision statistics. Correction-dependent fixes
older than 10 seconds are reported as stale rather than current.

## Run

After [installing the package](../README.md#running-the-examples), run these
commands from the `lib/um982py` directory.

Connect to a receiver:

```bash
python -m examples.position_tracking --port /dev/ttyUSB0 --duration 300 \
    --debug
```

`hgt` is the MSL height, while ellipsoidal height is `hgt + undulation`.

## Inputs and results

`--duration` and `--interval` control the capture. `--csv` writes tabular
fixes, and `--geojson` writes a track. Use `--help` for precision service and
geofence options.

## Understanding the result

The example selects receiver solutions using their type and correction age.
A track and estimated uncertainty do not prove absolute accuracy. Check the
correction service, reference frame and age, and compare with surveyed
positions when accuracy matters.

## References

[Unicore UM982 documentation](https://en.unicore.com/products/um982/).
