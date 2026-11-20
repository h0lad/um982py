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

### Read one position

Set `service` to `None` for the current solution, or choose `E6-HAS` or
`B2B-PPP` to start satellite PPP and read one sample.

```python
from um982py import Receiver

service = None  # Or "E6-HAS" / "B2B-PPP".
with Receiver.connect("/dev/ttyUSB0", 921600) as receiver:
    if service is None:
        position = receiver.best_navigation()
    else:
        position = receiver.start_ppp(service=service).position()

if position.valid:
    print(position.latitude, position.longitude)
    print("Solution:", position.position_type)
    if position.precision is not None:
        print("Horizontal RMS (m):", position.precision.horizontal_rms_m)
        print("Vertical std (m):", position.precision.up_std_m)
else:
    print("No position available yet")
```

### Watch precision over time

This recipe writes a CSV with fix type, convergence and receiver-reported
precision. Keep the antenna stationary when evaluating convergence.

```python
import csv
import sys
from time import monotonic, sleep

from um982py import Receiver

service = "E6-HAS"  # Or "B2B-PPP" / None for the current receiver solution.
duration_s = 600
interval_s = 5
writer = csv.writer(sys.stdout)
writer.writerow(
    [
        "elapsed_s",
        "gps_seconds",
        "solution",
        "valid",
        "converged",
        "horizontal_rms_m",
        "vertical_std_m",
        "correction_age_s",
    ]
)
try:
    with Receiver.connect("/dev/ttyUSB0", 921600) as receiver:
        ppp = receiver.start_ppp(service=service) if service is not None else None
        read_position = ppp.position if ppp is not None else receiver.best_navigation
        started = monotonic()
        while monotonic() - started < duration_s:
            position = read_position()
            precision = position.precision
            writer.writerow(
                [
                    round(monotonic() - started, 1),
                    position.epoch_gps_seconds,
                    position.position_type,
                    position.valid,
                    position.converged if ppp is not None else None,
                    precision.horizontal_rms_m if precision else None,
                    precision.up_std_m if precision else None,
                    position.correction_age_s,
                ]
            )
            sys.stdout.flush()
            sleep(interval_s)
except KeyboardInterrupt:
    pass
```

## Require sustained precision

The command-line convergence summary checks the last epoch against its targets.
For sustained application acceptance, use `ConvergenceMonitor` from
`um982py.convergence`. Choose limits for your application; these values are examples:

```python
from um982py import Position
from um982py.assessment import PositionLimits
from um982py.convergence import ConvergenceMonitor, ConvergenceStatus
from um982py.quality import FixClass

monitor = ConvergenceMonitor(
    PositionLimits(
        max_horizontal_rms_m=0.2,
        max_vertical_std_m=0.4,
        max_epoch_age_s=2,
        max_correction_age_s=30,
        allowed_fix_classes=frozenset({FixClass.PPP}),
    ),
    min_epochs=10,
    hold_seconds=30,
    max_gap_seconds=2,
    timeout=600,
)


def check_position(position: Position, current_gps_seconds: float) -> ConvergenceStatus:
    return monitor.observe(position, now_gps_seconds=current_gps_seconds)
```

Create the monitor after receiver configuration. Feed it positions about once
per second, with independently verified current GPST seconds. Use
`ppp.position(binary=False)` for the documented N4 ASCII `FINE` time status;
unverified binary time codes and date-less GGA cannot establish freshness.
Do not use the position's own epoch as the current time: that hides buffering.

`status.converged` requires the limits to hold over distinct epochs for at least
the requested receiver-time and host-time span. Duplicate epochs do not advance
the window. Bad quality, backwards epochs and gaps restart it. Inspect
`status.reasons` for the unmet checks. Call `monitor.status()` from a timer to
detect silence or ageing corrections even without new positions.
Stop when accepted or when `status.timed_out` is true; the monitor expires at
its deadline. Use a new monitor after a receiver/session/antenna change.
These checks assess reported quality, not independently verified accuracy.

## References

- Galileo HAS Signal-in-Space ICD.
- China Satellite Navigation Office (2020), PPP-B2b ICD.
- Sanz Subirana et al. (2012), GNSS Data Processing.
