# um982py

Python 3.12+ library and CLI for the Unicore UM982 GNSS receiver.

The receivers UM980 and UD960 might also work up to some extend 
but I didn't test due to lack of hardware.

Beware that my UM982 used the latest firmware r25164.

## Quick start

Install the package from a source checkout and query the receiver.

```bash
python -m pip install .
um982py --port /dev/ttyUSB0 --baud 921600 version
```

Use your receiver's port and baud rate. For a transparent UART gateway, use
`--port tcp://host:port` and set the UART baud rate on the gateway. Run
`um982py --help` for commands or use `doctor` to troubleshoot the connection.

```python
from um982py import Receiver

with Receiver.connect("/dev/ttyUSB0", 921600) as receiver:
    position = receiver.best_navigation()
    if position.valid:
        print(position.latitude, position.longitude, position.position_type)
```

## Find the right API

- Use `Receiver` for queries and bounded captures, or `AsyncReceiver` for asyncio.
- Use `Rover` for positions with optional NTRIP corrections and heading. The
  reconnecting live position example uses `um982py.live.PositionSession`.
- Use `record_observations()` for an in-memory capture or
  `um982py.session.SessionRecorder` for segmented disk recording.

## Examples

| Workflow | Example |
| --- | --- |
| Stream positions and reconnect | [Live position](examples/live_position/README.md) |
| Apply corrections | [NTRIP rover](examples/ntrip_client/README.md) or [satellite PPP](examples/has_b2b_ppp_fix/README.md) |
| Record or export observations | [Research session](examples/research_session/README.md) or [RINEX export](examples/rinex_export/README.md) |
| Analyze dual-antenna heading and velocity | [Heading engine](examples/rtk_quality/README.md#inspect-engine-covariance-and-satellite-states) or [Doppler velocity](examples/doppler_velocity/README.md) |

See the [example catalogue](examples/README.md) for setup and more workflows.

## Receiver output rates

```bash
um982py --port /dev/ttyUSB0 --baud 921600 output-rate --log GPGGA --rate-hz 10
```

In Python, use `receiver.set_output_rate(Log.GPGGA, 10)`. Available N4 rates
are 1, 2, 5, 10, 20 and 50 Hz, depending on the receiver, signal group and log.
`FREQJAMSTATUS`, `HWSTATUS`, `JAMSTATUS`, `PPSSTATUS` and `RTCSTATUS` are
limited to 1 Hz. Measure delivered cadence from distinct receiver epochs.

## RTK reliability

UM982 applies an RTK reliability threshold before it promotes a carrier-phase
solution into BESTNAV. Level 3 is the receiver default. Lower levels accept
float solutions sooner, while higher levels reject them more aggressively.
Use `rtk_reliability()` to change the live receiver setting:

```python
from um982py import Receiver
from um982py.commands.configuration import rtk_reliability

with Receiver.connect("/dev/ttyUSB0", 921600) as receiver:
    receiver.execute(rtk_reliability(2))  # RTK level 2, ADR default 1
```

The NTRIP rover and live position examples expose the same control through
`--rtk-reliability` and `--adr-reliability`. These options change receiver
settings and are not restored when the example exits. A lower threshold can
turn a `PSRDIFF` fallback back into `NARROW_FLOAT`, but it also increases the
risk of accepting an incorrect fix. Verify against a known coordinate before
trusting the result.

## Development

```bash
python -m pip install -e '.[dev]'
ruff check .
ruff format --check .
python -m mypy
python -m pytest -m 'not hardware'
```

Run live checks with `python -m pytest tests/hardware -m hardware
--hardware-port /dev/ttyUSB0 --hardware-baud 921600`. The
[test recording guide](tools/test_data_recorder/README.md) covers capture and
replay.

## License

[AGPLv3](LICENSE)
