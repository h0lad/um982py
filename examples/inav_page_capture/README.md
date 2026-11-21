# Galileo I/NAV page capture

Capture the decoded E1-B I/NAV page parts that the receiver stores per
tracked Galileo signal, assemble checksum-verified navigation words, and
report the Open Service Navigation Message Authentication (OSNMA) data they
carry.

## Run

Run from the repository root. The commands below use `PYTHONPATH=src`
to import the checkout directly. They require `pyserial`, which is
included in the [example installation](../README.md#running-the-examples).

`--helper` is the path of the RAM-resident reader image accepted by the
receiver boot menu. This repository ships one at
`tools/boot-reader/reader.bin` (380 bytes; its NDS32 assembly source
`um982_ram_reader.S` sits next to it and documents the upload protocol,
the read and reset requests and the rebuild steps); the option defaults to
that path, so from the repository root no extra argument is needed:

```bash
PYTHONPATH=src python3 -m examples.inav_page_capture --port /dev/ttyUSB0 --baud 921600 \
    --snapshots 3 --pause 10 --json pages.json
```

Pass `--helper` explicitly only when you keep the image somewhere else:

```bash
PYTHONPATH=src python3 -m examples.inav_page_capture --port /dev/ttyUSB0 \
    --helper /path/to/reader.bin --snapshots 3 --json pages.json
```

Close other serial clients first.

## Inputs and results

Each snapshot enters the boot menu, reads the per-signal tracking window
and resets the receiver back into the application. No flash write or erase
is performed; the application answers again after every closing reset and
the report records those answers.

With `--snapshots 1` the report lists one page part per tracked Galileo
signal: the PRN, the raw page bytes, whether the receiver marked the page
checksum-verified, and the decoded page-part fields. Odd nominal parts
carry the five-byte OSNMA field defined by the Galileo OSNMA SIS ICD:
eight HKROOT bits and thirty-two MACK bits per page.

With `--snapshots N` and a pause between captures, the stored part of each
channel advances with every completed page, so repeated snapshots
accumulate even and odd parts. The report then also contains navigation
words: every even part is paired with every odd part of the same PRN and
only pairs that pass the I/NAV page checksum of the Galileo Open Service
SIS ICD are kept. Word fields include the word type, the issue of data,
the satellite identifier and, for word type five, the Galileo system time.
These fields are the provenance payload for comparing against a broadcast
ephemeris log captured in parallel.

The report also contains an OSNMA activity summary per PRN (satellites
that do not transmit OSNMA send an all-zero field) and an independent
decode audit of the receiver's demodulation windows: the audit locates the
page synchronisation pattern in the coded symbol window, de-interleaves
the 240 following symbols and decodes them with the convolutional code of
the Open Service SIS ICD, judging the result by its own tail bits and
secondary synchronisation pattern. The decoded part is the one in flight at
the capture instant and is not expected to equal the stored page of the
same record.

The boot-menu snapshots provide raw OSNMA activity counts. The NMA header
occupies the first odd part of a GST-aligned sub-frame, so the snapshot
report leaves the legacy JSON `headers` list empty.

## Dump native GPS and GLONASS navigation

Live snapshots include parity-checked GPS and GLONASS bits in the terminal
tables and JSON by default. Pass `--no-native-nav` for a Galileo-only
report.

```bash
PYTHONPATH=src python3 -m examples.inav_page_capture --port /dev/ttyUSB0 --json nav.json
```

A saved tracking window collected from `TRACKING_MEMORY_BASE` can also
be read offline.

```bash
PYTHONPATH=src python3 -m examples.inav_page_capture --tracking-ram tracking.bin --json nav.json
```

`native_nav` contains one result per snapshot. GPS records carry ten
raw 30-bit LNAV words, the 24 data bits per word, the sub-frame ID and the
HOW time of the next sub-frame. All ten parity checks must pass.
GLONASS records carry the complete 85-bit FDMA string and its string
number. All eight Hamming checks must pass. Both retain the receiver
channel for provenance. The tracking layout was verified on UM982
snapshots. Stored records may precede the capture time or appear on
multiple channels.
[GPS IS-GPS-200N, §20.3.5](https://www.gps.gov/sites/default/files/2025-07/IS-GPS-200N.pdf)
· [GLONASS FDMA ICD, §4.7](https://www.unavco.org/help/glossary/docs/ICD_GLONASS_5.1_%282008%29_en.pdf)

## Record an experiment for offline analysis

```bash
PYTHONPATH=src python3 -m examples.inav_page_capture --port /dev/ttyUSB0 \
    --snapshots 3 --pause 10 --summary --save-tracking run/ram --json run/nav.json
```

`--summary` prints counts while the JSON keeps all raw fields. The
`snapshot_details` array includes the original Galileo parts, receiver
channel and time counter, the receiver's validity flag, and host UTC
bounds for each capture. The `native_nav` array follows the same snapshot
order. Galileo words listed under `words` have passed the page CRC.
Window audits include their one-based snapshot index.

`--save-tracking` creates a new directory and writes each completed
capture before the next pause. Each tracking window takes about 0.9 MiB.
Keep the `.metadata.json` sidecar with its `.bin` file to preserve the
capture bounds and let replay verify the SHA-256 checksum.

```bash
PYTHONPATH=src python3 -m examples.inav_page_capture \
    --tracking-ram run/ram/tracking-0001.bin --summary --json run/replay.json
```

Replay reconstructs the Galileo, GPS and GLONASS report without a serial
connection. Host UTC bounds cover the capture operation. Broadcast
message times and the receiver's tracking counters are separate fields.
Each live snapshot restarts the receiver. Measurements that require
uninterrupted page cadence, including complete SAR and OSNMA assembly,
need a continuous page stream.

## Replay a continuous Galileo stream

Pass an official-format I/NAV CSV and the corresponding trusted Galileo
public-key XML. This mode runs offline without opening the serial port.

```bash
PYTHONPATH=src python3 -m examples.inav_page_capture --stream-csv capture.csv \
    --public-key trusted-key.xml --json replay.json
```

The verifier uses CRC-checked word type 5 to align each satellite's
30-second sub-frames. It checks the assembled DSM-KROOT signature with
the supplied P-256 key, verifies the disclosed TESLA key from the next
sub-frame, and checks Tag0 against the preceding sub-frame's ADKD 0
navigation data. The JSON lists the signed roots and matching tags,
including the authenticated NMA status (`test` or `operational`).
GST fields pack the 12-bit week number above the 20-bit time of week.

The Python entry point is `um982py.experimental.verify_osnma_stream`.
Supply page parts in consecutive one-second slots per decimal SVID,
with empty bytes marking missing parts. The verifier covers nominal
SHA-256/HMAC-SHA-256 chains and reports historical cryptographic
matches. Capture-time freshness, key or chain lifecycle handling, and
multi-tag authentication thresholds require additional receiver logic.

## Replay search and rescue data

```bash
PYTHONPATH=src python3 -m examples.inav_page_capture --stream-csv capture.csv --sar-only
```

SAR replay counts CRC-checked fields and reports complete return-link
messages by satellite. Four consecutive I/NAV pages carry a short
message and eight carry a long message. The decoder checks even parity
across the 60-bit beacon ID, message code and all parameters. A short
message with code `1` and parameter prefix `10` is a Type 1
acknowledgement. Code `15` marks a test. The other code and parameter
combinations are spare, as are all long-message codes in the current
ICD. [Galileo Open Service SIS ICD, §§4.3.8 and 5.3](https://www.gsc-europa.eu/sites/default/files/sites/all/files/Galileo_OS_SIS_ICD_v2.2.pdf)

Spare fields are identified by two consecutive start bits of 1. The
bundled test stream uses alternating bits in those fields. Snapshot
reports show the raw 22-bit SAR field as six hex digits with two trailing
padding bits. The boot-menu captures sample isolated page parts, so
message assembly and spare classification require continuous replay.

The replay JSON includes the country code and protocol bits interpreted
as a first-generation Cospas-Sarsat beacon ID. For orbitography IDs with
valid modified-Baudot characters and a zero suffix, it also gives the
transmitted beacon label. The raw beacon ID and message parameters are
retained alongside the decoded fields. Snapshot JSON includes the raw
SAR field and a decoded start bit, length bit and twenty-bit payload.
[Cospas-Sarsat T.001, Annex A](https://sar.mot.go.th/document/THMCC/T001-MAR-26-2021%20SPECIFICATION%20FOR%20COSPAS-SARSAT%20406%20MHz%20DISTRESS%20BEACONS.pdf)

## Replay Galileo clock and ephemeris data

```bash
PYTHONPATH=src python3 -m examples.inav_page_capture --stream-csv capture.csv --ced-only
```

The replay decodes the eight signed RedCED parameters from CRC-checked
word 16 records. It reports the word bits, the scaled parameters and the
reference time when the stream has consistent Galileo timing words.
The reduced clock terms include radial-error compensation and belong
with the orbit parameters from the same RedCED word.

FEC2 replay groups CRC-checked clock, ephemeris and parity words by
satellite and GST sub-frame. It reports the four complete navigation
words when the available parity verifies or recovers them.
`recovered_types` identifies the words reconstructed from parity. The
Python function `um982py.experimental.recover_fec2_ced` can also work with
words assembled across sub-frames when the caller knows they belong to
the same satellite and issue of data. It handles erasures, with missing
or CRC-rejected pages treated as absent.
[Galileo Open Service SIS ICD, §§5.1.11, 5.1.13 and Annex F](https://www.gsc-europa.eu/sites/default/files/sites/all/files/Galileo_OS_SIS_ICD_v2.2.pdf)

## Understanding the result

`pages_with_osnma` counts the odd nominal parts. `words` lists the
checksum-verified word assemblies. `osnma_activity.prns` reports, per PRN,
whether any non-zero OSNMA field was observed. `window_audits` lists the
independent decodes. `application_restored` reports whether the
application responded after every closing reset.

## Human-readable dump

Without `--json`, stdout is the single JSON report and the human-readable
dump goes to stderr. With `--json FILE`, the report goes to the file and
the dump goes to stdout. The dump renders the same data as aligned tables:

```text
Galileo I/NAV page capture
==========================

Snapshots:             1
Pages:                 10 (10 unique)
PRNs:                  6, 7, 11, 12, 14, 15, 16, 20, 29, 36
Application restored:  yes

Captured page parts
-------------------
PRN    Ch  Part        Word  Valid  Page                              OSNMA       SAR
 11    76  odd/nom        -  yes    96c71102e24928a55246905500c0ebed  440b8924a2  954918

OSNMA activity
--------------
PRN  Odd  Nonzero  Observed
 11    1        1  yes

Checksum-verified words
----------------------
Word  IODnav  SVID  GST WN  TOW
   4      58     2       -  -

Window decode audits
--------------------
PRN  Sync  Errors  Tail    SSP  Decoded
```

Each section prints `-` when it has no rows. The legend below the tables
recalls what the part labels, the OSNMA field and the audits describe.

## References

Galileo Open Service SIS ICD: I/NAV page layout, convolutional code,
interleaving and page checksum.
[Galileo OSNMA SIS ICD](https://www.gsc-europa.eu/sites/default/files/sites/all/files/Galileo-OSNMA-SIS-ICD_in_force.pdf)
defines HKROOT, MACK, the TESLA chain and tag verification.
The [Galileo OSNMA Receiver Guidelines and Annex B test vectors](https://www.gsc-europa.eu/electronic-library/programme-reference-documents/galileo-in-force/osnma)
provide worked examples and replay streams.
