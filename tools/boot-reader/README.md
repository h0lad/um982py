# Boot-menu reader image

`reader.bin` is the RAM-resident reader image accepted by the receiver
boot menu. The page-capture example and the memory-read API upload it once
per session; while it is resident, it answers read requests for receiver
memory and a final reset request that restarts the application from flash.
No flash write or erase is requested at any stage of a session.

- Image: `reader.bin` (380 bytes, load address `0x200000`)
- SHA-256: `7ed2e04d4f78add28a58821880e2cb270012dc0ebd76a5343a8b6d63eb7b7358`
- Source: `um982_ram_reader.S` (NDS32 assembly, `NDS32:LE:32:default`)

## Use

The example and the capture API take the image path explicitly:

```bash
python -m examples.inav_page_capture --port /dev/ttyUSB0 --baud 921600 \
    --helper tools/boot-reader/reader.bin --snapshots 3 --json pages.json
```

```python
from pathlib import Path

from um982py.experimental import capture_inav_pages

pages = capture_inav_pages(
    "/dev/ttyUSB0", helper=Path("tools/boot-reader/reader.bin")
)
```

Both resolve the path exactly as given; run them from the repository root
or pass an absolute path.

## Protocol

The receiver boot menu receives the image as a downloadable record over
XMODEM. Once running, the reader transmits the banner `UM982RAM1` and
accepts three requests, each with little-endian 32-bit words:

| Request | Words | Operation |
|---|---|---|
| `M` | address, length | Read receiver memory; 1 to 4096 bytes |
| `Q` | none | Reset the receiver back into the application |

Every read answers with the marker `URD1`, the echoed address and length,
the data and a word sum over the returned bytes. The closing reset makes
the receiver leave the boot menu and start the application from flash;
the capture API verifies the application answers again afterwards.

## Rebuild

The shipped image is the assembled `um982_ram_reader.S`. Rebuild it with
an NDS32 GNU binutils (`as`, `ld`, `objcopy`):

```bash
nds32-as -o reader.o um982_ram_reader.S
nds32-ld -Ttext=0x200000 -o reader.elf reader.o
nds32-objcopy -O binary reader.elf reader.bin
```

The result must keep the load address `0x200000` and reproduce the banner
and the three requests above. Compare the SHA-256 of a rebuild against the
value above before replacing the shipped image.
