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

`--masks` selects the masks to compare. A live run collects one pass with the
receiver's current mask and applies every mask to the same observations, so
the steps differ only in the excluded satellites and the receiver
configuration is not changed. `--receiver-sweep` instead sets each mask on the
receiver and collects a new window per step. Those steps are separate in time,
so the mask effect is confounded with sky and multipath changes, and the
reported restoration state must be checked.

## References

- Braasch (1996).
- Unicore N4 R1.4 interface guide.
