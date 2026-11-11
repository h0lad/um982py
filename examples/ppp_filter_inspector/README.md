# PPP filter and RTOS performance inspector

Inspect the receiver's internal PPP filter telemetry.

## Run

Run from the repository root after [installation](../README.md#running-the-examples).

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

## Inputs and results

Missing fields are `null`.

## Understanding the result

The report keeps values with unverified units or meanings in their original form.

## References

- Zumberge et al. (1997), *Journal of Geophysical Research*, 102(B3).
- Galileo HAS SIS ICD, Issue 1.0 (2022).
