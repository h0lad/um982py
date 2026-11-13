# Time transfer

Convert receiver UTC to GPST using leap seconds.

## Run

Run from the repository root after [installation](../README.md#running-the-examples).

Connect to a receiver:

```bash
python -m examples.time_transfer --port /dev/ttyUSB0 --baud 921600 \
    --json out.json
```

Replay the supplied capture:

```bash
python -m examples.time_transfer --replay tests/fixtures/captures/TIMEB.bin
```

With 64-bit Python on Linux x86-64 or AArch64, read an already configured kernel
PPS device:

```bash
python -m examples.time_transfer.pps --device /dev/pps0 --count 5
```

Connect the device to the receiver's pulse output and configure it in the
operating system. See the [Linux PPS documentation](https://docs.kernel.org/driver-api/pps.html).

## Inputs and results

The report uses receiver TIME messages and their leap-second information.
Live capture requests binary TIME by default. Use `--ascii` to request ASCII.
Add `--pps-status` to also report the receiver's PPS status, GPS week,
millisecond of week, pulse error, observation offset, and raw configuration
and quality words. This is receiver status, not a timestamp from the host PPS
device. The PPS status may be absent if the receiver or firmware does not
provide the log.

## Understanding the result

The conversion checks the bundled leap-second table against the receiver's
TIME offset. If they disagree, it returns `offset_disagreement` without a GPST
result. Check the receiver and update or independently verify the table. Python
datetime cannot represent an inserted leap second, so these instants are rejected.

The PPS example reports host `CLOCK_REALTIME` timestamps. It does not match
pulses to receiver TIME messages, compensate for pulse delay or establish
timestamp accuracy. The host clock can step. Match the pulses and measure the
timing path before comparing them with receiver UTC.

## References

- Kaplan & Hegarty (2017).
- IERS leap seconds.
