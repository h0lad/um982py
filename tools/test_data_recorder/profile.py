"""Print receiver log commands for the test-recording profiles."""

import argparse
from collections.abc import Sequence

from um982py.commands import Log, Port, Trigger

Profile = tuple[tuple[Log, float | Trigger], ...]

CORE: Profile = (
    (Log.OBSVM, 1),
    (Log.OBSVH, 1),
    (Log.RANGE, 1),
    (Log.RANGEH, 1),
    (Log.GPSEPH, Trigger.ON_CHANGED),
    (Log.GLOEPH, Trigger.ON_CHANGED),
    (Log.GALEPH, Trigger.ON_CHANGED),
    (Log.BDSEPH, Trigger.ON_CHANGED),
    (Log.BD3EPH, Trigger.ON_CHANGED),
    (Log.QZSSEPH, Trigger.ON_CHANGED),
    (Log.BESTNAV, 1),
    (Log.BESTNAVH, 1),
    (Log.BSLNENUHD, Trigger.ON_CHANGED),
    (Log.SATVIS2, 10),
    (Log.RECTIME, 1),
    (Log.TIME, 1),
    (Log.GPSION, 60),
    (Log.GALION, 60),
    (Log.BDSION, 60),
    (Log.BD3ION, 60),
    (Log.GPSUTC, 60),
    (Log.GALUTC, 60),
    (Log.BDSUTC, 60),
    (Log.BD3UTC, 60),
    (Log.HWSTATUS, 60),
    (Log.ANTENNASTATUS, 60),
    (Log.RTKSTATUS, 10),
)
COMPRESSED: Profile = ((Log.OBSVMCMP, 1), (Log.OBSVHCMP, 1))
CORRECTIONS: Profile = (
    (Log.PPPNAV, 10),
    (Log.PPPNAVH, 10),
    (Log.RTCMSTATUS, Trigger.ON_CHANGED),
    *((Log(f"PPPB2BINFO{i}"), Trigger.ON_CHANGED) for i in range(1, 8)),
    (Log.E6MASKBLOCK, Trigger.ON_CHANGED),
    (Log.E6ORBITBLOCK, Trigger.ON_CHANGED),
    (Log.E6CLOCKFULLBLOCK, Trigger.ON_CHANGED),
    (Log.E6CLOCKSUBBLOCK, Trigger.ON_CHANGED),
    (Log.E6CBIASBLOCK, Trigger.ON_CHANGED),
    (Log.E6PBIASBLOCK, Trigger.ON_CHANGED),
)
TRACKED = CORE + COMPRESSED + CORRECTIONS


def select(*, compressed: bool = False, corrections: bool = False) -> Profile:
    """Return the requested output profile."""
    return (
        CORE + (COMPRESSED if compressed else ()) + (CORRECTIONS if corrections else ())
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compressed", action="store_true")
    parser.add_argument("--corrections", action="store_true")
    parser.add_argument("--port", choices=[port.value for port in Port])
    args = parser.parse_args(argv)
    port = Port(args.port) if args.port else None
    selected = select(compressed=args.compressed, corrections=args.corrections)
    for log, interval in selected:
        print(log.output(interval, binary=True, port=port).text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
