# Signal quality report

Reports C/N0 percentiles, lock time, and channel use.

## Run

After [installing the package](../README.md#running-the-examples), run these
commands from the `lib/um982py` directory.

Connect to a receiver:

```bash
python -m examples.signal_quality_report --port /dev/ttyUSB0 --baud 921600 \
    --json signals.json
```

Connect through a TCP gateway:

```bash
python -m examples.signal_quality_report --port tcp://192.0.2.10:4001 \
    --json signals.json
```

Replay the supplied capture:

```bash
python -m examples.signal_quality_report \
    --replay tests/fixtures/captures/RANGEB.bin
```

## Inputs and results

The report groups RANGE observations by signal and summarizes C/N0, lock time
and channel use. The TCP example uses a placeholder address, so replace it with
the address of your UART gateway.

## Understanding the result

The report groups observations by satellite signal and summarizes receiver
C/N₀, lock time and channel use. These diagnostics vary with the satellites,
antenna, cable and surroundings, so they do not provide calibrated antenna gain
or guarantee position accuracy.

## References

Unicore N4 R1.4 interface guide.
