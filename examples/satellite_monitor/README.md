# Satellite visibility monitor

Summarize satellite counts, azimuth and elevation by constellation using the
latest SATVIS2 epoch. Add `--csv` to save satellite positions for a sky plot.

## Run

Run from the repository root after [installation](../README.md#running-the-examples).

Connect to a receiver:

```bash
python -m examples.satellite_monitor --port /dev/ttyUSB0 --baud 921600 \
    --json vis.json
```

Replay the supplied capture:

```bash
python -m examples.satellite_monitor \
    --replay tests/fixtures/captures/SATVIS2A.bin --csv sky.csv
```

## Inputs and results

`--duration` and `--interval` control live SATVIS2 collection. Use `--mask` to
set an elevation cutoff in degrees.

`field_7` keeps its neutral name because the manual does not define it. On
R4.10Build25164 it equalled, to 0.01 dB-Hz, the RANGE C/N0 of the same epoch
for 3,900 of 3,900 compared satellites (2026-11-24): the primary signal (GPS
L1 C/A, GLONASS G1, Galileo E1-C, BeiDou B1I), or another tracked signal of
the satellite when the primary one was not tracked. `field_6` was always zero.

## Library usage

### Check satellite reception

```python
from um982py import Receiver

with Receiver.serial("/dev/ttyUSB0", 921600) as receiver:
    for satellite in receiver.satellites():
        print(satellite.constellation, satellite.prn)
        for signal in satellite.signals:
            print(f"  {signal.name or signal.signal_id}: SNR {signal.snr}")
```

## References

Kaplan & Hegarty (2017), Understanding GPS/GNSS.
