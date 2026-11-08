# Time transfer

Converts between GPST and UTC using leap seconds.

## Run

After [installing the package](../README.md#running-the-examples), run these
commands from the repository root.

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

The device must be connected to the receiver's pulse output and configured by
the operating system. See the [Linux PPS documentation](https://docs.kernel.org/driver-api/pps.html).

## Inputs and results

The report uses receiver TIME messages and their leap-second information.
Live capture requests binary TIME by default. Use `--ascii` to request ASCII.

## Understanding the result

GPS time (GPST) is a continuous GNSS time scale, while UTC is civil time and
differs by leap seconds. The conversion uses the leap-second information in
the bundled table and checks it against the receiver's TIME offset. A mismatch
returns `offset_disagreement` with no GPST result; update or independently check
the table and receiver. Python datetime cannot represent an inserted leap second,
so these instants are rejected.

The PPS example reports host `CLOCK_REALTIME` timestamps. It does not associate
the pulse with a receiver TIME message, compensate for pulse delay, or establish
timestamp accuracy. The host clock can step. Establish the association and
measure the timing path before comparing a pulse with receiver UTC.

## References

Kaplan & Hegarty (2017); IERS leap seconds.
