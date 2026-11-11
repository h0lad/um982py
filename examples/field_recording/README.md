# Field recording

Enable the desired receiver logs before recording, and describe the antenna,
reference point, receiver configuration, coordinate frame, time scale and
correction source in a JSON metadata file. Then record and replay:

```bash
python -m examples.field_recording record /dev/ttyUSB0 session \
  --baud 921600 --duration 3600 --metadata station.json
python -m examples.field_recording replay session
```

Choose a new destination directory. The recorder writes raw bytes in bounded
segments and journals their sizes, hashes and host timestamps. After a
transport failure, it reconnects and records the interruption as a gap.

Replay reports each gap and the size of any unfinished frame before it. It does
not join frames across a disconnection. Segment boundaries can fall inside a
frame.

An interruption can leave a `.part` file or a segment with no journal entry.
With `--allow-incomplete`, replay reads only journalled segments that pass
verification. The last segment may end inside a frame and cause a decode error.
Keep the other files for recovery and inspection. The journal's close marker
records that the sink closed, but does not confirm the requested duration.

The receiver must resume its enabled logs after reconnection. This example does
not configure them. Bytes lost before they reach the process cannot appear in
the recorder's loss counts.

See the [Unicore receiver reference](https://en.unicore.com/uploads/file/20241219/Unicore_Reference_Commands_Manual_For_N4_High_Precision_Products_V2_EN_R1.4.pdf) for available log formats.
