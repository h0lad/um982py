# Broadcast UTC and leap-second monitor

Read the UTC parameters that GPS, Galileo and BeiDou broadcast, and check
them against each other and against the receiver's own UTC offset. The
report gives GPST minus UTC as each system states it, any announced leap
second with its UTC date, the sub-second system-time offsets, and the
Galileo-GPS time offset (GGTO). No leap-second table is involved: every
value comes from the navigation messages.

## Run

Run from the repository root after [installation](../README.md#running-the-examples).

Connect to a receiver:

```bash
python -m examples.utc_leap_monitor --port /dev/ttyUSB0 --baud 921600 \
    --duration 60 --json utc.json
```

Replay the supplied capture of one session:

```bash
python -m examples.utc_leap_monitor --replay tests/fixtures/specialist/utc-parameters.bin
```

## Inputs and results

The monitor requests `IONUTC` (GPS), `GALUTC`, `BDSUTC` and `TIME`, and
evaluates everything at the latest `TIME` epoch. Each system's parameters
are mapped onto the GPS convention first: BeiDou weeks start at GPS week
1356 and count days 0 to 6, BDT runs 14 s behind GPST, and Galileo weeks
start at GPS week 1024.

The leap-second rule of IS-GPS-200 section 20.3.3.5.2.4 applies to every
system. `deltat_lsf` takes effect at the end of day `dn` of week `wn_lsf`.
`leap_second_announced` is true while that instant is still ahead, and
`leap_second_effective_utc` is the UTC midnight at which the new offset
starts.

`time_minus_utc_fraction_ns` is the A0 + A1 part of each system's UTC
model. `galileo_gps_time_offset` compares the broadcast GGTO with the
difference of the Galileo and GPS UTC models. Both describe the same GST
minus GPST, so a disagreement beyond `--tolerance-ns` raises an alarm.

The command exits with 1 and status `alarm` when:

- the systems disagree on GPST minus UTC or on a pending leap second;
- the receiver's `TIME` offset differs from the broadcast leap seconds;
- a system's UTC reference time lies more than a week from the epoch;
- the GGTO check exceeds its tolerance.

## Understanding the result

The supplied capture holds `TIME`, `GALUTC` and `BDSUTC` frames from one
session. Both systems agree with the receiver on 18 leap seconds, and
BeiDou's own value of 4 s plus the 14 s BDT offset gives the same result.
The repository's `IONUTC` capture is from a later week than the others, so
replaying it with this `TIME` frame correctly triggers the stale-reference
alarm.

A leap second is announced weeks in advance, and the systems update their
messages at different times. A brief disagreement between the systems
around an announcement is therefore expected and is not necessarily a fault.

## References

- [IS-GPS-200N, section 20.3.3.5.2.4](https://www.gps.gov/sites/default/files/2025-07/IS-GPS-200N.pdf)
- [Galileo OS SIS ICD v2.2, sections 5.1.7 and 5.1.8](https://www.gsc-europa.eu/sites/default/files/sites/all/files/Galileo_OS_SIS_ICD_v2.2.pdf)
- [BeiDou B1I ICD, section 5.2.4.17](https://www.unavco.org/help/glossary/docs/ICD_BeiDou_1.0_%282012%29_en.pdf)
