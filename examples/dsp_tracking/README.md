# DSP tracking snapshot

Read per-channel DSP tracking data from UM982 firmware R4.10Build25164.
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
tracker's phase flag is set. The GPS time tag is measured in milliseconds
of week and refers to the retained observation. Its week number is absent.
Use the time tags to check epoch alignment when comparing two channels.

Records include the constellation, band, carrier frequency and wavelength.
The additional positions recover GPS L2/L5, Galileo E5a/E5b/E6, BeiDou
B2a/B3 and GLONASS G2 from the observed dumps. For GLONASS, the RF channel
and the satellite identity are separate. A missing satellite identity
means the firmware has not assigned a receiver PRN to that channel.

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

The tracking heap can supply eight RF AGC codes in DSP order. These are
gain register codes. The optional windows also provide the following data
in JSON under `receiver_state`.

| Output | RAM source |
| --- | --- |
| GPS week and time of week in milliseconds | `0x13D443B0`, week at `+0x10` |
| Raw sensor channel and two ADC values | `0x13D42388` |
| GPS broadcast ionosphere alpha and beta coefficients and firmware flags | `0x13D704C4` |
| Retained diagnostic messages, including antenna status, RF AGC, and leap-second state | Diagnostic buffers at `0x402C00`, `0x404C00`, `0x406C08`, and `0x409C08` |

Replay automatically reads the additional files when present. Cached messages
carry their buffer address and may predate the binary state. Buffer order
does not establish chronology.

## References

- [Build 25164 layout and Python API](../../src/um982py/experimental/dsp_tracking.py)
- [Receiver-wide memory layout](../../src/um982py/experimental/dsp_receiver.py)
- [RAM reader protocol](../../tools/boot-reader/um982_ram_reader.S)
