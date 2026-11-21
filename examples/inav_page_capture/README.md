# Galileo I/NAV page capture

Capture the decoded E1-B I/NAV page parts that the receiver stores per
tracked Galileo signal, including the odd-part OSNMA protocol data.

## Run

Run from the repository root after [installation](../README.md#running-the-examples).

`--helper` is the path of the RAM-resident reader image accepted by the
receiver boot menu. Close other serial clients first:

```bash
python -m examples.inav_page_capture --port /dev/ttyUSB0 --baud 921600 \
    --helper /path/to/reader.bin --json pages.json
```

## Inputs and results

The capture enters the boot menu, reads the per-signal tracking window and
resets the receiver back into the application. No flash write or erase is
performed; the application answers again after the closing reset and the
report records that answer.

The report lists one page per tracked Galileo signal: the PRN, the raw page
bytes, whether the receiver marked the page checksum-verified, and the
decoded page-part fields. Odd nominal parts carry the five-byte OSNMA field
defined by the Galileo OSNMA SIS ICD: eight HKROOT bits and thirty-two MACK
bits per page. All E1-B pages of a sub-frame share one instant, so one
snapshot returns the same HKROOT portion for every satellite; assembling a
full HKROOT or MACK message requires fifteen consecutive odd pages of one
satellite and therefore repeated captures over at least one 30-second
sub-frame.

## Understanding the result

`pages_with_osnma` counts the odd nominal parts. `application_restored`
reports whether the application responded after the closing reset. A page
with `page_valid` false was still being verified at the capture instant and
its content is retained unchanged.

## References

Galileo Open Service SIS ICD, I/NAV page layout.
Galileo OSNMA SIS ICD, OSNMA data message.
