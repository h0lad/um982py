# Baseband notice console

Reconstruct the baseband configuration from diagnostic notices.

## Run

Run from the repository root after [installation](../README.md#running-the-examples).

Connect to a receiver:

```bash
python -m examples.baseband_notice_console --port /dev/ttyUSB0 --baud 921600 \
    --seconds 5 --enable-gate --record notices.bin --json state.json
```

Replay a capture:

```bash
python -m examples.baseband_notice_console --replay /tmp/notices.txt \
    --json state.json
```

## Inputs and results

`--seconds` sets the listening time. `--enable-gate` enables BBMSG2AP for the
capture and disables it afterward, even if it was already enabled. The previous
state cannot be queried. Replay requires captured notice data.

## Understanding the result

`solutions` counts NAVPOS lines. The report gives the worst residual between
the printed solutions and their ECEF coordinates, and the largest jump between
solutions. Distances are in metres.

## References

Unicore N4 R1.4 interface guide.
