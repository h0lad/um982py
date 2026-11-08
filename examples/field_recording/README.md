# Field recording

Enable the desired receiver logs before recording, and describe the antenna,
reference point, receiver configuration, coordinate frame, time scale and
correction source in a JSON metadata file. Then record and replay:

```bash
python -m examples.field_recording record /dev/ttyUSB0 session \
  --baud 921600 --duration 3600 --metadata station.json
python -m examples.field_recording replay session
```

The destination must not already exist. The session contains bounded raw byte
segments and a journal with their sizes, hashes and host timestamps. The
recorder reconnects after transport failures and records each interruption as a
gap. Replay reports gaps and the number of bytes in any unfinished frame before
the gap; it does not join frames across disconnected streams. Segments may
split a frame. An interruption can
leave a `.part` file or an unjournalled segment. `--allow-incomplete` replays
only verified journalled segments, which may end in a partial frame and cause a
decode error. Preserve the other files for recovery and inspection.
The journal's close marker means the sink was closed, not that a requested
occupation duration was reached.

The receiver's enabled logs must be restored by the device after reconnecting;
this example does not configure them. The recorder cannot measure bytes lost
before they reach the process. Protect recordings and metadata as appropriate
for their location and contents.

See the [Unicore receiver reference](https://en.unicore.com/uploads/file/20241219/Unicore_Reference_Commands_Manual_For_N4_High_Precision_Products_V2_EN_R1.4.pdf) for available log formats.
