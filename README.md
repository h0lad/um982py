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

## UM982 firmware diagnostics

The UM982 exposes additional logs through the existing `Log` API.
Examples include hardware and RTC status variants (`HWSTATUSD`, `RTCSTATUSD`),
PVT (`PVTSOL`), base-station observations (`BASESATS`), physical reference
station coordinates (`RTCM1032`), and internal correction tables
(`SSR1ORBIT`, `SSR1CLOCK`). SSR entries expose native coefficients and retain
their binary bytes. See the [mixed correction replay](examples/rtk_quality/README.md#inspect-a-mixed-correction-transcript)
for RTCM input and receiver-side diagnostics.
`SBAS1` and `SBAS18` expose masks, and the other SBAS logs retain their raw
bodies. `parse_mpt_debug()` exposes `time_pair_s` and
`diagnostic_blocks` alongside the original tokens. It also exposes the
positioning context's `ionosphere_snapshots`, `ionosphere_status`,
`correction_status` in `sav1`, `sav2` order, and `group_rows`. Pair each
snapshot with the corresponding public log epoch before comparing coefficients
with `snapshot.matches_public_log(record)`.

`scan_notices()` decodes `ClockAdjust Tag` and the four `$PPSDebug` forms
from a supplied trace. It preserves the native timing values and field order.

Use `um982py.binex.BinexEphemerisType` to subscribe to broadcast ephemerides
by constellation, alongside `binex_output()` for observations. `write_binex()`
exports both record families in capture order.

```python
from um982py import Log, Receiver
from um982py.experimental import base_mask_report, observation_mask_report

with Receiver.connect("/dev/ttyUSB0", 921600) as receiver:
    hardware = receiver.execute(Log.HWSTATUSD.read(binary=True))
    base_masks = receiver.collect(base_mask_report())
    observation_masks = receiver.collect(observation_mask_report())
```

Log availability depends on firmware, receiver state and incoming data.
`MASKBASE`, `MASKOBS` and seven SBAS log types were verified live.
`BASESATS` and SSR subscriptions registered on the receiver. Payload
validation for those logs requires a source of the corresponding corrections.
`SATXYZ2A` was verified live. The receiver rejected the `SATXYZ2B` command.

## Receiver output rates

```bash
um982py --port /dev/ttyUSB0 --baud 921600 output-rate --log GPGGA --rate-hz 10
```

In Python, use `receiver.set_output_rate(Log.GPGGA, 10)`. Available N4 rates
are 1, 2, 5, 10, 20 and 50 Hz, depending on the receiver, signal group and log.
`FREQJAMSTATUS`, `HWSTATUS`, `JAMSTATUS`, `PPSSTATUS` and `RTCSTATUS` are
limited to 1 Hz. Measure delivered cadence from distinct receiver epochs.

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
