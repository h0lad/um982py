# Time transfer

Converts between GPST and UTC using leap seconds.

## Run

After [installing the package](../README.md#running-the-examples), run these
commands from the `lib/um982py` directory.

Connect to a receiver:

```bash
python -m examples.time_transfer --port /dev/ttyUSB0 --baud 921600 \
    --json out.json
```

Replay the supplied capture:

```bash
python -m examples.time_transfer --replay tests/fixtures/captures/TIMEB.bin
```

## Inputs and results

The report uses receiver TIME messages and their leap-second information.
Live capture requests binary TIME by default. Use `--ascii` to request ASCII.

## Understanding the result

GPS time (GPST) is a continuous GNSS time scale, while UTC is civil time and
differs by leap seconds. The conversion uses the leap-second information in
the receiver's TIME records, so its result depends on the validity of those
fields and does not calibrate an external timing system.

## References

Kaplan & Hegarty (2017); IERS leap seconds.
