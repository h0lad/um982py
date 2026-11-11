# Post-processed RTK

With RTKLIB's `rnx2rtkp` installed, process rover and base observations and a
navigation file:

```bash
python -m examples.postprocessed_rtk rover.obs base.obs navigation.nav \
  --base-ecef X Y Z --reference-frame YOUR_FRAME --reference-epoch 2020.0 \
  --mode kinematic --output ppk-result
```

Replace the base ECEF coordinates with the surveyed antenna reference point in
metres, and identify its reference frame and coordinate epoch. Use a new output
directory. It will contain the RTKLIB solution and logs, plus a manifest with
input and executable hashes, the command and result counts.

Rover and base observations must overlap and contain compatible signals. Check
antenna offsets, time systems, signal mappings and the base coordinates before
interpreting the result. RTKLIB settings not exposed by this example use the
installed executable's defaults, which are recorded in its solution header.
The executable's quality codes and a successful run do not establish accuracy.

See [RTKLIB](https://github.com/tomojitakasu/RTKLIB) for solver details.
