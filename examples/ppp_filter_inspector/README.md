# PPP filter and RTOS performance inspector

Inspects the receiver's internal PPP filter telemetry.

## Run

After [installing the package](../README.md#running-the-examples), run these
commands from the `lib/um982py` directory.

Connect to a receiver:

```bash
python -m examples.ppp_filter_inspector --port /dev/ttyUSB0 --duration 4 \
    --record /tmp/ppp-debug.bin --json /tmp/ppp-debug.json
```

Replay a capture:

```bash
python -m examples.ppp_filter_inspector --replay /tmp/ppp-debug.bin \
    --json /tmp/ppp-replay.json
```

Parsed values keep their raw units, while missing fields are `null`.

## Inputs and results

The live command saves the wire capture with `--record`, while the second command
replays it. The report combines PPP debug fields with available auxiliary
telemetry, and values with unknown units remain in their native form.

## Understanding the result

The diagnostic summarizes available PPP filter fields and auxiliary telemetry,
retaining fields with unverified units or meanings in their native form. The
presence of a correction or debug field does not establish that the receiver
applied a particular correction.

## References

Zumberge et al. (1997), *Journal of Geophysical Research*,
102(B3); Galileo HAS SIS ICD, Issue 1.0 (2022).
