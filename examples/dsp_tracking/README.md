# DSP tracking snapshot

Read per-channel DSP tracking data from UM982 receivers.
The console shows Doppler, C/N₀, the raw carrier tuning word, and the last
stored pseudorange with its GPS time of week. JSON includes RF calibration,
lock and status fields, six diagnostic words, the normalized accumulator,
and the raw record bytes.

## Capture

Run from the repository root with the serial port free.

```bash
PYTHONPATH=src python3 -m examples.dsp_tracking --port /dev/ttyUSB0 \
    --save-ram dsp-snapshot --json dsp.json
```

By default the reader enters the boot menu from the running application.
If the receiver already shows the boot prompt, use:

```bash
PYTHONPATH=src python3 -m examples.dsp_tracking --port /dev/ttyUSB0 --boot-menu
```

With `--boot-menu` the reader waits for the boot prompt before sending
anything. Inside the boot menu it loads the RAM helper and uses its memory
read protocol. Application commands such as `RANGE`, `PTOBSINFO`, and
`RAWBBPKG` need the running receiver application. The helper resets the
receiver after the snapshot, and the example reports whether the
application responds again. The snapshot causes a break in live logging.
Use [raw baseband tracking](../raw_data_tracking/README.md) for application logs.

## Replay

```bash
PYTHONPATH=src python3 -m examples.dsp_tracking --replay dsp-snapshot --json replay.json
```

`--save-ram` creates a new directory with `tracking.bin`, `channels.bin`
and `rf_calibration.bin`. Replay works without the RF window and reports
unavailable Doppler as JSON `null`. New captures cover all seven frequency
positions in DSP measurement bank zero. Older archives with 157 channel
pointers still replay with the available positions. Snapshots can include
channels still acquiring. Collect `RANGE` while the application is running
when you need a continuous Doppler time series.

The JSON `observation` object also carries the DSP carrier phase in cycles,
its separately stored reference, their difference, and the internal epoch
counter. Phase uses the DSP sign convention and is reported when the
tracker's phase flag is set. The integer GPS time tag is measured in
milliseconds of week; its week number is absent.

`native_time_s` is the observation's fractional time tag, and
`native_time_scale` labels its scale. GPS and Galileo values are
seconds-of-week in GPST and GST, BeiDou values are seconds-of-week in BDT,
and GLONASS values are seconds-of-day in GLOT. The BDT tag is about 14
seconds behind GPST. GLOT is UTC(SU)+3h; conversion to GPST also requires
the date's leap-second offset and day rollover handling. Keep the native
scale when comparing records. The tag helps detect per-channel epoch skew;
the RAM windows are read sequentially, not atomically, and retained channel
records can be stale.

Records include the constellation, band, carrier frequency and wavelength.
The additional positions recover GPS L2/L5, Galileo E5a/E5b/E6, BeiDou
B2a/B3 and GLONASS G2 from captured snapshots. For GLONASS, the RF channel
and the satellite identity are separate. A missing satellite identity
means the receiver has not assigned a PRN to that channel.

The `observation` object also contains the receiver's pseudorange and phase
standard deviations, its phase-lock counter in milliseconds and its stored
Doppler for that epoch. The outer `doppler_hz` is reconstructed from the
carrier tuning word. The two Dopplers can differ. Apply the receiver's
standard deviations as model inputs and validate them against the residuals
of the experiment.

## Receiver-wide state

```bash
PYTHONPATH=src python3 -m examples.dsp_tracking --port /dev/ttyUSB0 \
    --receiver-state --save-ram dsp-full --json dsp-full.json
```

The tracking window can supply eight RF AGC codes in DSP order. These are
gain register codes. The optional windows also provide the following data
in JSON under `receiver_state`.

| Output | Description |
| --- | --- |
| GPS week and time of week in milliseconds | Receiver time at capture |
| Raw sensor channel and two ADC values | Unscaled sensor readings |
| GPS broadcast ionosphere alpha and beta coefficients and status flags | Navigation model supplied to the receiver |
| Retained diagnostic messages | Antenna status, RF gain state, and leap-second state |

Replay automatically reads the additional files when present. Cached messages
may predate the binary state. Buffer order does not establish chronology.

## Satellite positions

`--satellite-states` also reads four per-constellation state tables and writes
their valid entries under `satellite_positions` in JSON:

```bash
PYTHONPATH=src python3 -m examples.dsp_tracking --port /dev/ttyUSB0 \
    --satellite-states --save-ram dsp-orbits --json dsp-orbits.json
```

The output includes ECEF position (metres), velocity (metres per second),
state flags, and native-system time tags. The time-scale label is GPST, GST,
BDT, or GLOT. The second time tag is preserved without assigning it a role.
Entries marked unavailable or with non-finite position values are omitted.
Other state values remain undecoded. Captures are not atomic, and state tags
can predate the snapshot time. These are geometry states, not broadcast
ephemeris parameters.

Live states from all four constellations were checked against same-issue
broadcast ephemerides propagated to each record's own state time. Position
residuals were at most 0.4 km and ECEF velocity differences at most 0.14 m/s.
Some residuals are near zero and others cluster around 0.3 km, following the
ephemeris issue time; this is broadcast-orbit accuracy, not an external
precise-orbit product. `SATECEF` is not a same-epoch reference: its positions
were 3.0–3.5 km from the same broadcast ephemerides at the `SATECEF` header
time, and its 10-second offset from the DSP state time adds about 30 km of
satellite motion. Older archives with shorter GPS or GLONASS windows replay
as record-aligned prefixes; only the captured entries are decoded.

## References

- [DSP tracking layout and Python API](../../src/um982py/experimental/dsp_tracking.py)
- [Receiver-wide memory layout](../../src/um982py/experimental/dsp_receiver.py)
- [RAM reader protocol](../../tools/boot-reader/um982_ram_reader.S)
