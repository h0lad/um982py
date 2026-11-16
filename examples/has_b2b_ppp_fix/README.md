# Dual-service PPP fix with divergence telemetry

At a stationary point, collect PPP positions and E6-HAS/B2b correction telemetry.
The report averages available positions and gives precision statistics.

## Run

Run from the repository root after [installation](../README.md#running-the-examples).

Connect to a receiver:

```bash
python -m examples.has_b2b_ppp_fix --port /dev/ttyUSB0 --baud 921600 --augment \
    --ppp-service AUTO --duration 600 --debug --json /tmp/has-b2b-fix.json \
    --csv /tmp/has-b2b-epochs.csv
```

Replay a capture:

```bash
python -m examples.has_b2b_ppp_fix --replay captures/has-b2b.bin \
    --json /tmp/replay-fix.json
```

Run the cyclic example:

```bash
python -m examples.has_b2b_ppp_fix.cyclic --port /dev/ttyUSB0 --cycles 12 \
    --cycle-seconds 5 --debug --json /tmp/cyclic.json
```

`--augment` requests signal group 3/6 and PPP `AUTO`, the receiver's automatic
service selection. The receiver saves a changed signal group and reboots.
The `cyclic` example subscribes to PPPNAV once and passes each pushed fix and
its running mean to a callback without polling the receiver.

## Inputs and results

`--duration` controls the recording time, and `--csv` saves per-epoch results.
`--target-h-sigma`, `--target-v-sigma` and `--min-ppp` set precision and sample
criteria.

## Library usage

### Watch a precise position converge

Keep the antenna stationary. Stop with Ctrl+C:

```python
from um982py import Receiver
from um982py.geodesy import haversine_distance

with Receiver.serial("/dev/ttyUSB0", 921600) as receiver:
    ppp = receiver.start_ppp(service="E6-HAS")
    previous = None
    try:
        for fix in ppp.poll_positions(interval=5):
            precision = fix.precision
            print(
                f"{fix.position_type}: horizontal RMS "
                f"{precision.horizontal_rms_m if precision else None} m, "
                f"height std {precision.up_std_m if precision else None} m, "
                f"correction age {fix.correction_age_s} s"
            )
            if fix.valid and fix.latitude is not None and fix.longitude is not None:
                position = (fix.latitude, fix.longitude)
                print(f"Position: {position}")
                if previous is not None:
                    print(f"Change: {haversine_distance(*previous, *position):.3f} m")
                previous = position
            else:
                previous = None
    except KeyboardInterrupt:
        print("Stopped")
```

Use `service="B2B-PPP"` for BeiDou PPP-B2b or `service="L6MDCPPP"` for QZSS
MADOCA PPP. `start_ppp()` changes the signal group and PPP service if needed.
The receiver saves a changed signal group and reboots; PPP service changes are
not explicitly saved. The session reports which settings changed. Group 7/0
supports B2b in base mode; `start_ppp()` checks the mode before using it.

For QZSS MADOCA correction telemetry, run:

```bash
um982py --port /dev/ttyUSB0 --baud 921600 --madoca ppp-diagnostics
```

Receiving correction messages does not confirm that the receiver applied them.

## References

- Galileo HAS Signal-in-Space ICD.
- China Satellite Navigation Office (2020), PPP-B2b ICD.
- Sanz Subirana et al. (2012), GNSS Data Processing.
