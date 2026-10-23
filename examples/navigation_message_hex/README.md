# Navigation messages in hex

Dumps navigation messages as annotated hex.

## Run

After [installing the package](../README.md#running-the-examples), run these
commands from the `lib/um982py` directory.

Connect to a receiver:

```bash
python -m examples.navigation_message_hex --port /dev/ttyUSB0 --baud 921600 \
    --seconds 20
```

Replay the supplied capture:

```bash
python -m examples.navigation_message_hex \
    --replay tests/fixtures/captures-live/GPSEPHB.bin --seconds 2
```

## Inputs and results

Use `--family` or `--log` to restrict the messages of interest and `--seconds`
to set the live collection time. The annotated hex is useful for inspecting
captured wire messages.

## Understanding the result

This diagnostic displays selected navigation messages as annotated hexadecimal
wire data. The available messages depend on the families received during the
selected capture window.

## References

Unicore N4 R1.4 interface guide.
