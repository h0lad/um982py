# Baseband notice console

Rebuilds baseband configuration from diagnostic notices.

## Run

After [installing the package](../README.md#running-the-examples), run these
commands from the `lib/um982py` directory.

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
capture and disables it afterward. Because the prior gate state cannot be
queried, the example cannot restore an earlier enabled state. Replay requires
previously captured notice data.

## Understanding the result

The tool reconstructs configuration information from baseband notices received
during the selected capture window. The optional gate changes receiver state as
described below.

The `solutions` payload entry summarises the baseband position lines: how many
NAVPOS lines arrived, their worst self-consistency residual against the ECEF
triple printed on the same line, and the largest jump between consecutive
solutions, all in metres.

## References

Unicore N4 R1.4 interface guide.
