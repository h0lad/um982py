# Multipath and elevation masks

Sweeps elevation masks and checks receiver state.

## Run

After [installing the package](../README.md#running-the-examples), run these
commands from the `lib/um982py` directory.

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

## Understanding the result

This experiment compares receiver measurements at different elevation masks,
the minimum angle above the horizon for accepting a satellite. A higher mask
can reject low-angle signals while also reducing satellite availability.

A live sweep changes receiver settings and attempts restoration afterward.
Inspect the reported restoration state and do not assume a particular mask
will improve every position solution.

## References

Braasch (1996); Unicore N4 R1.4 interface guide.
