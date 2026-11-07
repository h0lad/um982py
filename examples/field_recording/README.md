# Field recording

Enable the desired receiver logs before recording, and describe the antenna,
reference point, receiver configuration, coordinate frame, time scale and
correction source in a JSON metadata file. Then record and replay:

```sh
python -m examples.field_recording record /dev/ttyUSB0 session \
  --baud 921600 --duration 3600 --metadata station.json
python -m examples.field_recording replay session
```

The destination must not already exist. The session contains bounded raw byte
segments and a journal with their sizes, hashes and host timestamps. Segments
may split a frame; replay decodes the concatenated stream. An interruption can
leave a `.part` file or an unjournalled segment. `--allow-incomplete` replays
only verified journalled segments, which may end in a partial frame and cause a
decode error. Preserve the other files for recovery and inspection.
The journal's close marker means the sink was closed, not that a requested
occupation duration was reached.

This example uses one receiver connection and does not measure bytes lost
before they reach the process. Protect recordings and metadata as appropriate
for their location and contents.
