# Galileo I/NAV page capture

Capture the decoded E1-B I/NAV page parts that the receiver stores per
tracked Galileo signal, assemble checksum-verified navigation words, and
report the Open Service Navigation Message Authentication (OSNMA) data they
carry.

## Run

Run from the repository root after [installation](../README.md#running-the-examples).

`--helper` is the path of the RAM-resident reader image accepted by the
receiver boot menu. Close other serial clients first:

```bash
python -m examples.inav_page_capture --port /dev/ttyUSB0 --baud 921600 \
    --helper /path/to/reader.bin --snapshots 3 --pause 10 --json pages.json
```

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

Assembling a complete OSNMA sub-frame needs fifteen consecutive odd pages
of one satellite; the campaign accumulates parts toward that goal, but a
boot-menu capture per page is slow and the official stream format of the
Galileo OSNMA test vectors exercises the same verification chain much more
directly. The library modules
`um982py.experimental.osnma` and `um982py.experimental.ecdsa_p256` verify a
DSM-KROOT signature with a public key from the Galileo key directory,
derive and verify the TESLA chain keys, and verify the tag and sequence
fields of a MACK message; the module tests demonstrate every step with
the published worked example and a stream test vector.

## Understanding the result

`pages_with_osnma` counts the odd nominal parts. `words` lists the
checksum-verified word assemblies. `osnma_activity.prns` reports, per PRN,
whether any non-zero OSNMA field was observed. `window_audits` lists the
independent decodes. `application_restored` reports whether the
application responded after every closing reset.

## References

Galileo Open Service SIS ICD: I/NAV page layout, convolutional code,
interleaving and page checksum.
Galileo OSNMA SIS ICD: OSNMA data message, HKROOT, MACK, TESLA chain and
tag verification.
Galileo OSNMA Receiver Guidelines: worked example and test vectors.
