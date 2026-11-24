# Live position

Show live GGA fixes from a receiver and reconnect after a transport failure.
On a terminal, the output is a self-refreshing dashboard with the receiver's
fix type, position and velocity uncertainty, DOP and basic GNSS statistics.
Redirecting output, or passing `--plain`, writes one line per distinct fix.

```bash
python -m examples.live_position /dev/ttyUSB0 --baud 921600 --interval 1
python -m examples.live_position /dev/ttyUSB0 --baud 921600 --rate-hz 10
python -m examples.live_position /dev/ttyUSB0 --plain --correction-service e6-has

# rtk2go public caster, mountpoint Weinstadt
export NTRIP_USERNAME=you@example.com
python -m examples.live_position /dev/ttyUSB0 --baud 921600 --interval 1 --ntrip

# accept float RTK sooner on a short baseline
python -m examples.live_position /dev/ttyUSB0 --interval 1 --ntrip --rtk-reliability 2
```

`--ntrip` relays `http://rtk2go.com:2101/Weinstadt` into the receiver. The
caster requires a registered, well-formed email username; set `NTRIP_USERNAME`
or pass `--ntrip-username`. The password defaults to `none` for rtk2go. Use
`--ntrip-url` for another caster and `NTRIP_PASSWORD` when it needs a real
password. `--ntrip-version 1` selects NTRIP 1.0. Weinstadt requires rover GGA,
which the relay supplies from the subscribed stream. Relay state, RTCM frame
count, correction age and terminal errors appear in the NTRIP row. A rejected
login does not stop the position display.

`--rtk-reliability` sets the receiver's RTK reliability threshold to 1, 2, 3 or
4, from low to high. Lower values accept float solutions sooner and increase
the risk of a wrong fix. The receiver default is 3. `--adr-reliability` sets
the carrier-phase threshold separately. Both settings change live receiver
configuration on each connection and are not restored on exit. Neither option
is needed when the receiver is already configured as desired.

The example enables GPGGA, BESTNAVB and DOPPVELB output on each connection and
leaves those subscriptions configured on the receiver. GGA is required. The
other logs are optional, and a rejected log is reported on stderr and in the
dashboard without stopping the stream. Stop with Ctrl-C. For a TCP connection,
use a target such as `tcp://host:port`. Use `--no-doppler` when the receiver
does not provide DOPPVEL. Pass `--request-gsa` only on receivers that accept
that log. DOP values are still read when the receiver already streams GSA.

Choose either `--interval` in seconds or `--rate-hz` in Hertz. The receiver and
firmware determine the actual output rate. All requested logs use the same
rate.

Quality labels, detailed position-type labels, DOPPVEL decoding and GSA
decoding come from `um982py.messages`. The example only adds host arrival
timing, terminal rendering and the declared correction-service label.

The dashboard shows two fix-type layers. GGA quality supplies the familiar
standalone, DGPS, RTK fixed and RTK float labels. BESTNAV supplies the
receiver's detailed position type, including `NARROW_INT`, `PPP` and its INS
variants. GGA does not identify the correction service. Use
`--correction-service e6-has`, `b2b-ppp`, `l6-madoca` or `auto` to label the
service you have configured. The panel marks it as declared. Without that
option, the panel shows an RTCM base station when GGA reports one, or notes
that a PPP service is unknown. A declared service is marked `unused` while the
fix is standalone. It never infers E6-HAS from a fix type alone.

Position uncertainty comes from the one-sigma east, north and up deviations in
BESTNAV. Deviations switch between mm, cm and m so small and large values stay
readable. DOP values come from GSA. Doppler speed is shown in m/s and km/h, with
the narrow layout showing km/h. Speed deviations come from DOPPVEL. These are
receiver estimates, not accuracy bounds. GGA alone
has no position standard deviations. To pair GGA with receiver-reported GST
error ellipses, use the [position precision example](../position_precision/README.md).

DOPPVEL is a receiver-computed Doppler solution that shares observations with
the position fix. It is not a raw Doppler measurement or an independent
accuracy check. The newest Doppler sample within two seconds of the displayed
GGA arrival supplies ground speed, course over ground and vertical speed. When
speed is below twice its reported deviation, course is hidden and the motion
line is marked `noisy`. A small speed history is drawn as a sparkline on wide
terminals.

The panel uses a compact layout below 106 columns and a wider layout above it.
Both versions fit inside the terminal width. ANSI colour is limited to status,
speed and secondary text, and the panel uses clear-to-end redraws so a short
terminal does not accumulate stale rows.

`PositionSession` reports host arrival time separately from the receiver's GGA
UTC time of day. Missing measurements remain `None`. On the tested UM982, both
`GPGGA` and `GNGGA` were active and the firmware emitted two byte-identical
`GNGGA` sentences about 1 ms apart for every epoch. Stopping `GNGGA` leaves one
sentence per second; the example leaves receiver settings alone and collapses
frames with the same UTC time, position, satellites, HDOP and correction age.
The dashboard still refreshes while no new fix arrives, and the panel counts
suppressed duplicates.

The example subscribes to the receiver's decoded frame stream through
`PositionSession(subscribe=True)` instead of driving reads from the consumer
loop. A `ReceiverStream` owns each connection and dispatches GGA, BESTNAV,
DOPPVEL and any streamed GSA frames to the display monitors. The queue wait is
only used to react to the stop event.

After confirming that the receiver outputs WGS 84 coordinates, pass `--geojson`
for GeoJSON lines. GeoJSON height, when available, is ellipsoidal height. The
fix type, detailed position type and Doppler speed are added to the feature
properties.

The optional `--max-gap` and `--max-correction-age` checks report assessment
reasons with each fix. A background check also reports health changes on stderr
when no new fix arrives. Applications can call `PositionMonitor.status()` or
check the session health from another thread. `status()` reports
`position_unavailable` before the first update and `position_stale` when its
age exceeds `max_gap_s`. It also advances the last receiver-reported correction
age by the time since arrival. This does not include receiver or transport
latency. Connection health remains available separately from
`PositionSession.health()`.

For an application with an update callback and a timer, use the same monitor
in both callbacks:

```python
from um982py.live_quality import LiveLimits, PositionMonitor

monitor = PositionMonitor(LiveLimits(max_gap_s=3, max_correction_age_s=5))


def on_position(update):
    monitor.observe(update)


def on_timer():
    status = monitor.status()
    if not status.accepted:
        print("Position unavailable:", status.reasons)
```

Register `on_position` with the code consuming `PositionSession.positions()`
and run `on_timer` independently, so it also runs during a receiver outage.
`PositionSession` also accepts an `on_message` callback for every decoded
frame before GGA filtering. The callback must not raise or use the receiver.

See the [Unicore receiver reference](https://en.unicore.com/uploads/file/20241219/Unicore_Reference_Commands_Manual_For_N4_High_Precision_Products_V2_EN_R1.4.pdf) for GGA output.
