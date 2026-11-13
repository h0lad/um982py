# Live position

Print GGA fixes from a receiver and reconnect after a transport failure:

```bash
python -m examples.live_position /dev/ttyUSB0 --baud 921600 --interval 1
python -m examples.live_position /dev/ttyUSB0 --baud 921600 --rate-hz 10
```

The example enables GPGGA output on each connection and leaves it configured
on the receiver. Stop it with Ctrl-C. For a TCP connection, use a target such
as `tcp://host:port`.

Choose either `--interval` in seconds or `--rate-hz` in Hertz. The receiver and
firmware determine the actual output rate.

`PositionSession` reports host arrival time separately from the receiver's GGA
UTC time of day. Missing measurements remain `None`. The session does not add
heading, speed or uncertainty from other messages. `health()` exposes the
connection state and most recent fix time. Set a staleness limit and monitor
health while consuming positions.

After confirming that the receiver outputs WGS 84 coordinates, pass `--geojson`
for GeoJSON lines. GeoJSON height, when available, is ellipsoidal height.
GGA alone does not contain position standard deviations. To pair GGA with
receiver-reported GST error ellipses, use the [position precision
example](../position_precision/README.md).

The optional `--max-gap` and `--max-correction-age` checks report assessment
reasons with each fix. A background check also reports health changes on stderr
when no new fix arrives. Applications can call `PositionMonitor.status()` or
check the session health from another thread. `status()` reports `position_unavailable`
before the first update and `position_stale` when its age exceeds `max_gap_s`.
It also advances the last receiver-reported correction age by the time since
arrival. This does not include receiver or transport latency. Connection health
remains available separately from `PositionSession.health()`.

For an application with an update callback and a timer, use the same monitor
in both callbacks:

```python
from um982py import LiveLimits, PositionMonitor

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

See the [Unicore receiver reference](https://en.unicore.com/uploads/file/20241219/Unicore_Reference_Commands_Manual_For_N4_High_Precision_Products_V2_EN_R1.4.pdf) for GGA output.
