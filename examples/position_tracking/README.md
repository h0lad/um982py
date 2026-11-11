# Position tracking

Collect position fixes and precision statistics. Fixes that depend on
corrections older than 10 seconds appear as stale.

## Run

Run from the repository root after [installation](../README.md#running-the-examples).

Connect to a receiver:

```bash
python -m examples.position_tracking --port /dev/ttyUSB0 --duration 300 \
    --debug
python -m examples.position_tracking --port /dev/ttyUSB0 --duration 30 \
    --rate-hz 10 --debug
```

`hgt` is the MSL height, while ellipsoidal height is `hgt + undulation`.

## Inputs and results

`--duration` and `--interval` control the capture. Use `--rate-hz` instead of
`--interval` to request a periodic output rate in Hertz. The example subscribes
to several logs. Each log's supported rates depend on the receiver, firmware
and signal group. `--csv` writes tabular fixes, and `--geojson` writes a track.
Use `--help` for precision service and geofence options.

## References

[Unicore UM982 documentation](https://en.unicore.com/products/um982/).
