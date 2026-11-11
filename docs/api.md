# API guide

Connect to a UM982 through a serial port or a transparent TCP-to-UART gateway.

## Connect and read a position

```python
from um982py import Receiver

with Receiver.connect("/dev/ttyUSB0", 921600) as receiver:
    position = receiver.best_navigation()
    if position.valid:
        print(position.latitude, position.longitude, position.height_std_m)
```

Use `Receiver.connect("tcp://host:port")` for a TCP gateway. `receiver.fix()`
returns a GGA `Fix`. `receiver.heading()` reads the heading between the two
antennas. `best_navigation()` also returns velocity and the receiver's estimates
of standard deviation.

`SolutionStatus` and `PositionType` name the known status and position codes.
The library preserves unknown codes as the receiver reports them.

Use `receiver.positions(interval=1)` to query GGA positions repeatedly, with a
pause of one second between queries. The receiver stays open when the loop ends.

## Rover and field workflows

`Rover.connect(target, baudrate, ntrip_url=..., username=..., password=...)`
opens a receiver and forwards NTRIP corrections in the background. Configure
rover mode first, then pass your provider's URL and credentials. The session
does not configure the receiver. Position queries use the same connection.
To read positions without NTRIP, omit `ntrip_url`.

Use the rover as a context manager to close its connection and correction
worker on exit. Closing waits for pending I/O to finish. With an existing
receiver, `Rover(receiver, ...)` leaves the receiver open.

`rover.correction_health()` reports the connection state and correction
forwarding progress. If the relay encounters a fatal error, the next position
query raises it. `rover.wait_for_fix(...)` and `rover.survey_point(...)` run
the GGA workflows while the relay forwards corrections.

`rover.position()` and `rover.positions()` return a `RoverPosition` with a
BESTNAV solution in `position`. The `heading_deg` and `pitch_deg` fields come
from UNIHEADING. They require a computed float or fixed heading within
`heading_tolerance` seconds of the position epoch. If either condition fails,
both fields are `None`. `heading_type` gives the solution type, and
`heading_offset_s` gives the difference between the epochs.

Separate queries read position and heading, so their epochs may differ. Pass
`heading=False` to query position only. For a valid differential or RTK position,
`correction_age_s` gives the differential age reported by the receiver. It is
`None` for a standalone fix. The relay separately tracks the time since it last
forwarded an RTCM frame.

To control correction forwarding directly, use `RtkSession` with a
`ReceiverStream`.

```python
from um982py import Receiver, survey_point, wait_for_fix

with Receiver.connect("/dev/ttyUSB0", 921600) as receiver:
    fix = wait_for_fix(receiver, timeout=120, rtk_fixed=True, max_correction_age=5)
    point = survey_point(receiver, duration=60, rtk_fixed=True, max_correction_age=5)
    print(fix.latitude, fix.longitude)
    print(point.latitude, point.longitude, point.ellipsoidal_height_m)
    print(point.samples, point.horizontal_scatter_m)
    point.write_csv("survey-point.csv")
```

`wait_for_fix` raises `ResponseTimeout` if no fix meets the criteria before the
deadline. For `survey_point`, keep the antenna stationary and use WGS 84
positions. The survey rejects invalid fixes, missing heights and repeated GGA
times. It needs at least two distinct epochs.

The scatter measures repeatability, not absolute accuracy or uncertainty of
the mean. Base-station errors and correlated measurements remain in the result.
Review the coordinates before using them for a base station. CSV export refuses
to overwrite an existing file.

```python
from um982py import Receiver, TrackWriter, waypoint_direction

with Receiver.connect("/dev/ttyUSB0", 921600) as receiver:
    with TrackWriter("walk.gpx", format="gpx", reference_frame="WGS84") as track:
        for fix in receiver.positions(interval=1):
            if fix.valid:
                track.write(fix)
                direction = waypoint_direction(
                    fix.latitude, fix.longitude, 52.52, 13.40
                )
                print(direction.distance_m, direction.bearing_deg)
```

`TrackWriter` writes GPX, GeoJSON or CSV as fixes arrive. It creates a new file
and refuses to overwrite an existing one. If you have a verified timestamp,
pass a timezone-aware `datetime` as `timestamp=`. GGA supplies a time of day but
no date.

GPX uses MSL height. GeoJSON uses ellipsoidal height and stores the fixes as a
collection of points. Start a new track after a gap in the data.

To replay BESTNAV frames, iterate over `iter_frames(path)`, select messages with
`Log.BESTNAV.request(...).matches()`, and convert them with
`BestNavigation.from_message(message)` before writing.
Before using `message_utc(message, leap_seconds=...)`, verify the GPS–UTC offset
and receiver time status. `waypoint_direction` calculates directions on a
spherical Earth. Pass the vehicle's true heading as `heading_deg` to get a
signed turn angle.

Each polling query discards other received messages unless you pass an
`on_message` callback. The callback receives each message in arrival order,
including messages following the reply in the same read. Messages already queued
before the query remain available through `receive()` or `drain_pending()`.
The callback runs inside the transaction and must not call receiver methods.
For `AsyncReceiver.positions()`, the callback runs in a worker thread.

## Receiver output rates

Set the output rate in Hz for each periodic log. One call can configure several
logs. Commands use the current receiver port unless you select a port:

```python
from um982py import Log, Receiver
from um982py.commands import Port

with Receiver.connect("/dev/ttyUSB0", 921600) as receiver:
    receiver.set_output_rate([Log.GPGGA, Log.BESTNAV], 10, port=Port.COM1, verify=True)
    for entry in receiver.log_list().entries:
        print(entry.port, entry.name, entry.rate_hz)
```

Select the receiver port wired to your host, such as `COM1` above. The API uses
binary output when the log supports it and ASCII otherwise. To require the same
format for all selected logs, pass `binary=False` or `True`. Use
`antenna_log(log, "secondary")` for a documented secondary-antenna log.

With `verify=True`, you must select a port. The method checks the configured
interval in `LOGLIST`. This confirms the setting but does not measure the rate
of log output or position solutions. For `ONCHANGED` subscriptions,
`LogEntry.rate_hz` is `None` because output follows events.

`await async_receiver.set_output_rate(...)` provides the same API for asyncio.
When a `ReceiverStream` or `Rover` owns the receiver, use its
`set_output_rate(...)` method. `ReceiverStream` returns a future.

```bash
um982py --port /dev/ttyUSB0 --baud 921600 output-rate \
  --log GPGGA --log BESTNAV --rate-hz 10 --output-port COM1 --verify-rate
```

The CLI defaults to ASCII logs. `--binary` requires binary output for every
selected log. The command leaves the signal group unchanged and does not send
`SAVECONFIG`.

If one command fails, earlier changes remain active. A command can also change
settings before the receiver rejects it or the reply times out. The exception
and CLI output list the commands acknowledged before the failure.

The documented N4 periodic rates are 1, 2, 5, 10, 20 and 50 Hz. A 50 Hz rate is
limited to specific N4 products and firmware. Unicore specifies 20 Hz RTK and
heading for the UM982. Its command manual qualifies 20 Hz in signal group 3/6
by firmware and log. It does not establish that every log or signal group
supports that rate. These references do not document 100 Hz N4 output, so the
API rejects `rate_hz=100`.

The receiver can reject a valid command, cap the rate or deliver data more
slowly. Check the recorded epochs to measure the actual rate and the port
throughput to assess capacity.
Changing `SIGNALGROUP` can reset the receiver and be saved automatically. This
API does not change it.

To test an interval outside the documented rate list, specify seconds directly:
`receiver.execute(Log.GPGGA.output(interval=0.01))`. This requests 100 Hz. Support
depends on the receiver, log and firmware. Check the command response,
`LOGLIST` and recorded epochs.

At the command level, `Log.BESTNAV.output(rate_hz=10)` builds the same request.
Use either `interval` in seconds or `rate_hz` in Hz. For a temporary recording,
call `capture_live(receiver, Log.RANGE, duration=30, rate_hz=10)`. The capture
restores the previous subscriptions when it ends. `iter_live_records` accepts
the same option for streaming.

ONCHANGED-only and one-shot logs do not accept `rate_hz`.
`receiver.positions(interval=...)` and `rover.positions(...)` pause between
queries. Their interval does not set the receiver's output rate.

Capture and replay preserve the receiver's messages, including repeated epochs.
They do not interpolate, fill gaps or duplicate measurements to reach a
requested rate. Repeated queries can return the same epoch. Use distinct
receiver timestamps to measure the native rate.

For timestamped logs such as BESTNAV, check the receiver's time status and
inspect the spacing between recorded epochs. This example reports the median
rate and largest gap:

```python
from itertools import pairwise
from statistics import median

from um982py import Log, Receiver, capture_live
from um982py.capture import record_epoch

with Receiver.connect("/dev/ttyUSB0", 921600) as receiver:
    records = capture_live(receiver, Log.BESTNAV, duration=10, rate_hz=10)

epochs = [record_epoch(record) for record in records]
intervals = [later - earlier for earlier, later in pairwise(epochs)]
if intervals and all(interval > 0 for interval in intervals):
    print(
        "Median rate:", 1 / median(intervals), "Hz; largest gap:", max(intervals), "s"
    )
else:
    print("Not enough ordered epochs to measure the rate")
```

Sources: [Unicore N4 command reference, data output commands](https://en.unicore.com/uploads/file/Unicore%20Reference%20Commands%20Manual%20For%20N4%20High%20Precision%20Products_V2_EN_R1.3.pdf),
[UM982 product specifications](https://en.unicorecomm.com/products/um982/),
and [N4 signal-group configuration](https://en.unicore.com/uploads/file/unicore-reference-commands-manual-for-n4-high-precision-products-v2-en-r1.2.pdf).

## Satellites and measurements

`receiver.satellites()` returns `Satellite` objects with a constellation, PRN,
angles and `signals`. Each `SatelliteSignal` includes a name, receiver-reported
SNR and the original system and signal IDs. Unknown names are `None`.

`receiver.range_samples()` returns supported observations in SI units. For a
recorded series, use `sample_series(records)`. Optional `systems` and `signals`
filters use receiver tracking-status IDs. Each observation needs a known carrier
frequency and usable code and phase. The conversion omits observations that
fail these checks. GLONASS frequencies use the reported channel or an explicit
`glonass_channels` mapping.

## Galileo HAS and BeiDou PPP-B2b

```python
from um982py import Receiver

with Receiver.connect("/dev/ttyUSB0", 921600) as receiver:
    ppp = receiver.start_ppp(service="E6-HAS")
    for position in ppp.positions(interval=5):
        print(position.position_type, position.horizontal_std_m)
```

`PppSession.positions()` and `AsyncPppSession.positions()` use the same
`on_message` and queued-message rules as `receiver.positions()`. The async
callback runs in the worker thread.

Use `service="B2B-PPP"` or `"AUTO"` to select another service. `start_ppp()` checks
the receiver configuration and changes the signal group and service if needed.
`PppSession` records the previous settings and which ones changed. Changes
remain active for the receiver session without saving them to persistent
configuration or restoring them on exit. A signal-group change can restart
acquisition.

`PppSolution.valid` identifies a computed PPP position. `converged` reports the
receiver's solution type. Selecting a service does not show which corrections
the receiver used. Establish that from the receiver's output.

## Logs, captures and RINEX

`Log` contains both documented and extended receiver logs. Use the same type for
one-shot queries and captures:

```python
from um982py import Log, Receiver, capture_live, export_rinex

with Receiver.connect("/dev/ttyUSB0", 921600) as receiver:
    records = capture_live(receiver, Log.RANGE, duration=60)

result = export_rinex(records, marker_name="FIELD01")
result.write("field.obs")
```

`load_records(path, log)` reads a saved capture, and `decode_message(data)`
decodes one checksummed frame. When binary message IDs are ambiguous, pass the
intended `log` to `decode_message`. RTCM decoding exposes its message type and
payload.
`RinexExport.write()` and `RinexNavigationExport.write()` replace existing files.

`capture_live` stores decoded records in memory. `duration` limits the collection
time, not its size in bytes. For incremental processing, use
`um982py.stream_capture.iter_live_records()`. For longer raw recordings, use
`um982py.session.SessionRecorder`.

With one log, `frames` can end the capture early. This limit excludes SATVIS2
because one epoch can span several frames. With multiple logs, the capture runs
for the full duration. Each selected log must have a distinct name.

On Ctrl+C during collection, `InterruptedCapture` contains the records received
so far in a dictionary, even when capturing a single log. For example:

```python
from um982py import InterruptedCapture, Log, Receiver, capture_live

with Receiver.connect("/dev/ttyUSB0", 921600) as receiver:
    try:
        observations = capture_live(receiver, Log.RANGE, duration=60)
    except InterruptedCapture as interrupted:
        observations = interrupted.records[Log.RANGE.value]

print(f"Collected {len(observations)} observation records")
```

The capture attempts to restore subscriptions when it ends, including after an
interruption. Restoration can fail if the receiver disconnects. Before
post-processing a partial capture, check its metadata and missing observations.

## Receiver time

`message_utc(record, leap_seconds=...)` converts a timestamped record or frame
to an aware UTC `datetime`. Supply a verified GPS–UTC offset valid for the
observation epoch. For a non-GPS receiver time reference, also supply the
verified `week_scale`. `gps_to_utc(week, seconds_of_week, leap_seconds=...)`
converts an explicit GPS week and time of week. Check the receiver's time status
before using a timestamp.

## Asyncio and errors

`AsyncReceiver.connect()` supports asynchronous `fix()`, `best_navigation()`,
`heading()`, `satellites()`, `positions()` and `start_ppp()` calls.
`await receiver.start_ppp()` returns a session. Await its `position()` method
for one result, or use `async for` over its `positions()` method.

Receiver and protocol errors are defined in `um982py.errors`. For example,
`ResponseTimeout` reports a missing reply, and `CommandRejected` carries the
rejected command and receiver response. See the [example catalogue](../examples/README.md)
for complete applications and `help()` on individual objects for their parameters.

For statistical functions, use `um982py.stats`. Satellite geometry calculations
are in `um982py.geometry`, and SLAS decoders are in `um982py.slas`. Use
`um982py.state` to restore receiver settings.
