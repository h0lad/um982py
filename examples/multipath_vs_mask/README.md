# Multipath and elevation masks

Compare elevation masks and check the receiver state after each sweep.

## Run

Run from the repository root after [installation](../README.md#running-the-examples).

Connect to a receiver:

```bash
python -m examples.multipath_vs_mask --port /dev/ttyUSB0 --baud 921600 \
    --json out.json
```

Replay a capture:

```bash
python -m examples.multipath_vs_mask --replay /tmp/mask-pass.bin \
    --json /tmp/mask.json
```

## Inputs and results

`--masks` selects the masks to compare. Live sweeps change receiver settings,
so use a receiver whose configuration can be temporarily changed and check the
reported restoration state.

## References

- Braasch (1996).
- Unicore N4 R1.4 interface guide.
