# API guide

`um982py` talks to a UM982 through a serial port or a transparent TCP-to-UART
gateway. The examples below assume an installed package and a configured receiver.

## Connect and read a position

```python
from um982py import Receiver

with Receiver.connect("/dev/ttyUSB0", 921600) as receiver:
    position = receiver.best_navigation()
    if position.valid:
        print(position.latitude, position.longitude, position.height_std_m)
```

Use `Receiver.connect("tcp://host:port")` for a TCP gateway. `receiver.fix()`
returns a GGA `Fix`, and `receiver.heading()` reads the dual-antenna heading.
`best_navigation()` includes velocity and receiver-estimated standard deviations.
Known solution statuses and position types use `SolutionStatus` and
`PositionType` enums; unknown receiver values remain available as reported.

For repeated GGA queries, iterate over `receiver.positions(interval=1)`.
Each iteration polls the receiver, and the interval is the pause between queries.
Breaking the loop leaves the receiver open for other operations.

## Rover and field workflows

`Rover.connect(target, baudrate, ntrip_url=..., username=..., password=...)`
opens a receiver and runs NTRIP corrections in the background while position
queries use the same receiver. Use it as a context manager. Configure rover mode
beforehand; the session does not alter receiver settings. Pass the provider's
actual URL and credentials, or omit `ntrip_url` for positioning without NTRIP.
`rover.correction_health()` reports forwarding and connection state. Fatal relay
errors surface on the next position query; closing waits for in-flight I/O.
`Rover(receiver, ...)` instead borrows an existing receiver and leaves it open.
`rover.wait_for_fix(...)` and `rover.survey_point(...)` perform the corresponding
GGA workflows while the correction relay is active.

`rover.position()` and `rover.positions()` return `RoverPosition`: its
`position` is a BESTNAV solution, and `heading_deg` and `pitch_deg` come from
UNIHEADING only when it has a computed float or fixed heading and its receiver epoch is
within `heading_tolerance` seconds of the position. Otherwise they are `None`.
`heading_type` reports the solution type and `heading_offset_s` records the epoch difference. This is polling, so separate
queries do not guarantee matching epochs. Pass `heading=False` for position
only. `correction_age_s` is the receiver-reported differential age for a valid
differential or RTK position; it is `None` for an ordinary standalone fix. It
is distinct from the relay's age of the last forwarded RTCM frame.

The old blocking `relay_ntrip()` helper has been removed. Use `Rover` when
reading positions alongside corrections, or `RtkSession` with a
`ReceiverStream` when direct control of the relay is needed.

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

`wait_for_fix` raises `ResponseTimeout` when its deadline expires. Surveying
assumes a stationary antenna and WGS 84 positions, and rejects invalid fixes,
missing heights, and repeated GGA time-of-day values. It needs at least two
distinct epochs. The reported sample scatter is repeatability, not absolute
accuracy or the uncertainty of the mean; base errors and correlated errors
remain. The result is not automatically a surveyed base coordinate. CSV export
creates a new file and does not overwrite an existing one.

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

`TrackWriter` streams GPX, GeoJSON or CSV into a new file and refuses to
overwrite an existing one. Supply `timestamp=` with a verified timezone-aware
`datetime` when available; GGA contains a time of day but no date. GPX uses MSL
height, and GeoJSON uses ellipsoidal height and writes a collection of points.
Start a new track across missing data. To replay BESTNAV frames, iterate over
`iter_frames(path)`, select messages with `Log.BESTNAV.request(...).matches()`,
and convert them with `BestNavigation.from_message(message)` before writing.
Use `message_utc(message, leap_seconds=...)` only with a verified GPS–UTC offset
and receiver time status. `waypoint_direction` uses a spherical Earth and
accepts an optional true vehicle `heading_deg` to calculate a signed turn angle;
it does not plan a route.

During each polling query, other received messages are discarded unless you pass
an `on_message` callback. The callback receives each message in arrival order,
including messages following the reply in the same read. Messages already queued
before the query remain available through `receive()` or `drain_pending()`.
The callback runs inside the transaction and must not call receiver methods.
For `AsyncReceiver.positions()`, the callback runs in a worker thread.

## Satellites and measurements

`receiver.satellites()` returns `Satellite` objects with a constellation, PRN,
angles and `signals`. Each `SatelliteSignal` includes a name, receiver-reported
SNR and the original system and signal IDs. Unknown names are `None`.

`receiver.range_samples()` returns supported observations in SI units. For a
recorded series, use `sample_series(records)`. Optional `systems` and `signals`
filters use receiver tracking-status IDs. Observations with unknown carrier
frequencies or unusable code and phase are omitted. GLONASS frequencies use the
reported channel or an explicit `glonass_channels` mapping.

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

Use `service="B2B-PPP"` or `"AUTO"` to select another service. Setup verifies
receiver configuration and changes the signal group and service when needed.
The `PppSession` reports previous settings and which settings changed. These
settings remain active for the receiver session; setup neither saves nor restores
them. A signal-group change can restart acquisition.

`PppSolution.valid` identifies a computed PPP position, while `converged`
reports the receiver's solution type. The selected service is configuration;
check receiver evidence separately to establish which corrections were applied.

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

`capture_live` restores the subscriptions it changes. `load_records(path, log)`
reads a saved capture, and `decode_message(data)` decodes one checksummed frame.
When binary message IDs are ambiguous, pass the intended `log` to
`decode_message`. RTCM decoding exposes its message type and payload.
`RinexExport.write()` and `RinexNavigationExport.write()` replace existing files.

`capture_live` holds decoded records in memory. Its `duration` bounds collection
time, not the number of bytes; use `um982py.stream_capture.iter_live_records()`
for incremental processing or `um982py.session.SessionRecorder` for longer raw
recordings. A `frames` limit stops a single-log capture early, except for SATVIS2,
whose epochs may span multiple frames. With multiple logs, collection runs for
the requested duration. Give each selected log a distinct name.

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

The receiver attempts subscription restoration on exit, including interruption;
a disconnected receiver may prevent restoration. Check capture completeness and
metadata before using partial observations for post-processing.

## Receiver time

`message_utc(record, leap_seconds=...)` converts a timestamped record or frame
to an aware UTC `datetime`. Supply a verified GPS–UTC offset valid for the
observation epoch. For a non-GPS receiver time reference, also supply the
verified `week_scale`. `gps_to_utc(week, seconds_of_week, leap_seconds=...)`
converts an explicit GPS week and time of week. Check the receiver's time status
before using a timestamp.

## Asyncio and errors

`AsyncReceiver.connect()` provides asynchronous `fix()`, `best_navigation()`,
`heading()`, `satellites()`, `positions()` and `start_ppp()` operations. A PPP
session returned by `await receiver.start_ppp()` provides `await position()`
and `async for` over `positions()`.

Receiver and protocol errors are defined in `um982py.errors`. For example,
`ResponseTimeout` reports a missing reply, and `CommandRejected` carries the
rejected command and receiver response. See the [example catalogue](../examples/README.md)
for complete applications and `help()` on individual objects for their parameters.

Specialist tools live in their own modules: `um982py.stats` provides statistical
functions, `um982py.geometry` covers satellite geometry, `um982py.slas` decodes
SLAS corrections, and `um982py.state` handles receiver-state restoration.
