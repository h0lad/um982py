# Galileo I/NAV page capture

Capture the decoded E1-B I/NAV page parts that the receiver stores per
tracked Galileo signal, assemble checksum-verified navigation words, and
report the Open Service Navigation Message Authentication (OSNMA) data they
carry.

## Run

Run from the repository root after [installation](../README.md#running-the-examples).

`--helper` is the path of the RAM-resident reader image accepted by the
receiver boot menu. This repository ships one at
`tools/boot-reader/reader.bin` (380 bytes; its NDS32 assembly source
`um982_ram_reader.S` sits next to it and documents the upload protocol,
the read and reset requests and the rebuild steps); the option defaults to
that path, so from the repository root no extra argument is needed:

```bash
python -m examples.inav_page_capture --port /dev/ttyUSB0 --baud 921600 \
    --snapshots 3 --pause 10 --json pages.json
```

Pass `--helper` explicitly only when you keep the image somewhere else:

```bash
python -m examples.inav_page_capture --port /dev/ttyUSB0 \
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

## Replay a continuous Galileo stream

Pass an official-format I/NAV CSV and the corresponding trusted Galileo
public-key XML. This mode runs offline without opening the serial port.

```bash
python -m examples.inav_page_capture --stream-csv capture.csv \
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
PRN    Ch  Part        Word  Valid  Page                              OSNMA
 11    76  odd/nom        -  yes    96c71102e24928a55246905500c0ebed  440b8924a2

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
