# Signal quality report

Summarize C/N0 percentiles, lock time and channel use.

## Run

Run from the repository root after [installation](../README.md#running-the-examples).

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

Replace the TCP example's placeholder address with the address of your UART
gateway. The report groups RANGE observations by signal.

## Understanding the result

The C/N₀ values include the effects of the antenna, cable and surroundings.
They are not calibrated antenna gain measurements.

## References

Unicore N4 R1.4 interface guide.
