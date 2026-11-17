# um982py

Python 3.12+ library and CLI for the Unicore UM982 GNSS receiver: receiver
control, RTK/PPP positions, observation recording, and offline analysis.

UM960 and UM980 have not been tested.

## Install and use

From a source checkout:

```bash
python -m pip install .
um982py --port /dev/ttyUSB0 --baud 921600 version
um982py --port tcp://192.0.2.10:4001 doctor
```

Match the port and baud rate to your receiver; the default is 115200 baud.
For a transparent TCP-to-UART gateway, configure its UART baud rate separately.
Use `--help` for commands and `doctor` to investigate connection problems.

### Read one position

Choose a source by setting `service` in either example below:

| `service` | Position source |
| --- | --- |
| `None` | Current receiver solution (BESTNAV); leaves configuration unchanged. |
| `"E6-HAS"` | Enable Galileo E6-HAS and read the PPP solution. |
| `"B2B-PPP"` | Enable BeiDou PPP-B2b and read the PPP solution. |

Satellite PPP requires a suitable antenna and service reception. Enabling it
can change the signal group and reboot the receiver; configuration remains active
after closing the connection. A standard read does not disable existing corrections.

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

`position.valid` means usable coordinates are available; PPP may still be
converging. A PPP result also has `position.converged`, reflecting the receiver's
solution state. Starting a service does not wait for convergence.

### Watch precision over time

Keep the antenna stationary for a convergence trial. Choose the service, duration
and polling interval below. Run until the duration expires, or stop with Ctrl+C.
The output is CSV: save the snippet as `watch_position.py` and run
`python watch_position.py > precision.csv`. Plot `horizontal_rms_m` and
`vertical_std_m` against `elapsed_s`, or omit the redirect to watch live output.

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

Watch the PPP state change and the reported deviations settle; convergence time
and achievable precision depend on reception and conditions. Blank values mean
unavailable, not zero. Repeated GPS epochs are the same measurement.
Horizontal RMS is the root-sum-square of east/north deviations, not a 95% radius;
these are receiver estimates, not verified accuracy. For saved reports with
precision targets, see the [PPP example](examples/has_b2b_ppp_fix/README.md);
for GGA/GST statistics, see [position precision](examples/position_precision/README.md).

For a sustained acceptance window with freshness checks and a timeout, use
[`ConvergenceMonitor`](examples/has_b2b_ppp_fix/README.md#require-sustained-precision).

## Choose a workflow

Start with one of three paths:

1. **Read positions:** `Receiver.best_navigation()` for one native solution;
   `Receiver.stream_positions()` for live GGA updates. Keep solution quality,
   measurement epoch, and host arrival time distinct.
2. **Run a corrected rover:** `Rover` combines receiver and correction workflows.
   See the NTRIP and satellite PPP examples below. Correction bytes received or
   forwarded do not prove that the receiver applied them.
3. **Record and analyze:** `record_observations()` returns a bounded in-memory
   `Observations`; use `SessionRecorder` for segmented disk recording. Preserve
   raw bytes and receiver/session/antenna identity before filtering or export.

| Goal | Starting point |
| --- | --- |
| Follow a live position | [Live tracking](examples/live_position/README.md) |
| Apply real-time corrections | [NTRIP rover](examples/ntrip_client/README.md) or [satellite PPP](examples/has_b2b_ppp_fix/README.md) |
| Record or export observations | [Research session](examples/research_session/README.md) or [RINEX export](examples/rinex_export/README.md) |
| Survey a stationary point | [Static occupation](examples/precise_fix/README.md) |
| Measure dual-antenna orientation | [Heading and attitude](examples/heading_attitude/README.md) |
| Inspect satellites and reception | [Satellite monitor](examples/satellite_monitor/README.md) or [signal quality](examples/signal_quality_report/README.md) |
| Work with receiver time and PPS | [Time transfer](examples/time_transfer/README.md) |

The [example catalogue](examples/README.md) covers all workflows, required data,
and limits of the scientific models. Examples run from the source checkout.

## Choose a connection and streaming model

Start with `Receiver` for queries and captures, or `Rover` for BESTNAV positions
with optional NTRIP corrections and heading. Advanced components use explicit
module imports:

| API | Ownership and behavior | Reconnects |
| --- | --- | --- |
| `receiver.poll_positions()` | Repeated GGA queries on the caller's receiver. | No |
| `receiver.stream_positions()` / `capture_live()` | Temporary output subscriptions; restore settings and leave the receiver open. | No |
| `Rover` | Owns a worker; `Rover.connect()` also owns the receiver. A supplied receiver stays open unless `close_receiver=True`. | Caster |
| `um982py.live.PositionSession` | Owns fresh receivers from a factory; reads emitted GGA. Configure output explicitly if needed. | Receiver |
| `um982py.rover_session.RoverSession` | Owns fresh receivers and rover workers; polls BESTNAV with optional NTRIP. | Receiver and caster |
| `um982py.streaming.ReceiverStream` | Worker for concurrent commands and bounded subscriptions; receiver closure is configurable. | No |
| `um982py.rtk_session.RtkSession` | Correction relay borrowing an existing `ReceiverStream`; owns caster connections. | Caster |

`live.PositionSubscription` adapts a worker subscription to GGA updates.
`session.SessionRecorder` records raw files and manifests. Neither reconnects
the receiver. Do not read directly from a receiver while a worker owns it.
Close iterators when stopping early so cleanup runs.

With an open receiver, subscribe to positions for a fixed duration:

```python
with receiver.stream_positions(duration=60, rate_hz=1) as positions:
    for position in positions:
        if position.valid:
            print(position.latitude, position.longitude)
```

`AsyncReceiver` supports `async with` and `async for`. `capture_live()` returns
a dictionary keyed by log name, even for one log. Captures preserve native
epochs; they do not interpolate or duplicate samples.

## Common workflows

### Use a corrected rover

Configure rover mode first and supply your caster details. Pass `username` and
`password` if required. On exit, this closes the receiver and correction worker.

```python
from um982py import Rover

with Rover.connect(
    "/dev/ttyUSB0", 921600, ntrip_url="https://caster.example:443/MOUNT"
) as rover:
    for update in rover.poll_positions(interval=1, heading=True):
        if update.position.valid:
            print(update.position.latitude, update.position.longitude)
            print(
                "Heading:",
                update.heading_deg,
                "correction age:",
                update.correction_age_s,
            )
```

Heading is optional and requires two antennas with a valid, epoch-matched
baseline. Apply the measured mounting offset for vehicle orientation.
Receiving corrections alone does not establish an RTK fix.

### Record observations for post-processing

```python
from um982py import Receiver, record_observations

with Receiver.serial("/dev/ttyUSB0", 921600) as receiver:
    observations = record_observations(receiver, duration=60)

result = observations.to_rinex(marker_name="FIELD01")
result.write("field.obs")
print(f"Saved {result.epochs} epochs; omitted observations: {result.omitted}")
```

This holds records in memory and replaces an existing output file. For long
recordings, use the [unattended station](examples/unattended_station/README.md).
Keep one receiver session and antenna per series. Review omissions, station
metadata, and phase alignment before precise processing; compressed OBSV
carrier phases remain unavailable. See [RINEX export](examples/rinex_export/README.md).
Live captures retain receiver/session/antenna source tags; see
[observation identity](examples/research_session/README.md#preserve-observation-identity)
for recording and restoring them during replay.

## Receiver output rates

```bash
um982py --port /dev/ttyUSB0 --baud 921600 output-rate --log GPGGA --rate-hz 10
```

In Python, use `receiver.set_output_rate(Log.GPGGA, 10)`. N4 rates are
1, 2, 5, 10, 20 and 50 Hz, subject to receiver, firmware, signal group and log.
[UM982 specifies up to 20 Hz RTK and heading](https://en.unicorecomm.com/products/um982/);
50 Hz is product-specific. `FREQJAMSTATUS`, `HWSTATUS`, `JAMSTATUS`, `PPSSTATUS`
and `RTCSTATUS` are limited to 1 Hz.

`verify=True` requires a `port` and checks `LOGLIST`. Measure delivered rates
from distinct receiver epochs and inspect gaps. `poll_positions(interval=...)`
controls the pause between queries. Rate changes do not save settings or change
the signal group; a failed multi-log change can leave earlier changes active.

`--augment` and `start_ppp()` may change the signal group, which the receiver
saves before rebooting. A reboot can discard other unsaved settings; other
augmentation changes are not explicitly saved. See the
[PPP example](examples/has_b2b_ppp_fix/README.md) for service selection.

## Development

See [ARCHITECTURE.md](ARCHITECTURE.md) for layer boundaries and validation priorities.

```bash
python -m pip install -e '.[dev]'
ruff check .
ruff format --check .
python -m mypy
python -m pytest
```

## License

AGPLv3
