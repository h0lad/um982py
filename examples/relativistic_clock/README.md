# Relativistic satellite clock term

GPS, Galileo and BeiDou orbits are slightly elliptical. A satellite clock
therefore runs faster near apogee, where the satellite is higher and
slower, and slower near perigee. The broadcast clock polynomial leaves this
periodic effect, `Δtr = F e √A sin E`, to the user. This example shows how
large the term is for each satellite and how far a GPS position moves when
it is left out.

## Run

Run from the repository root after [installation](../README.md#running-the-examples).

Connect to a receiver:

```bash
python -m examples.relativistic_clock --port /dev/ttyUSB0 --baud 921600 \
    --duration 30 --json relativity.json
```

Replay the supplied capture:

```bash
python -m examples.relativistic_clock \
    --replay tests/fixtures/specialist/relativity-session.bin
```

## Inputs and results

The example collects `RANGE` together with `GPSEPH`, `GALEPH` and
`BDSEPH`. Each RANGE epoch is solved twice with the GPS L1 weighted
least-squares solver of [`wls_position`](../wls_position/README.md):
once with the complete broadcast clock, and once without its relativistic
term. Both solutions start from the Earth's centre, so no prior position is
needed.

`position_shift_without_relativity` gives the median horizontal, vertical
and receiver-clock displacement. The report contains only differences
between the two solutions, never the position itself. `gps_terms_used`
lists the term that each satellite contributed. `orbit_amplitudes` ranks
every received orbit by its peak term `2 √(μA) e / c²`, which is reached a
quarter orbit from perigee.

## Understanding the result

In the supplied capture, G24 (e = 0.019) has the largest term, ±43.5 ns or
13 m of range. Leaving the term out moves the position by about 7.6 m
horizontally. Part of the error is common to all satellites and goes into
the receiver clock, but the rest differs between satellites and distorts
the geometry. Galileo E14 and E18, launched into an eccentric orbit
(e ≈ 0.16), carry a term of several hundred nanoseconds, over 100 m.

The term is distinct from the constant frequency offset that is applied
to every satellite clock before launch. That offset compensates the mean
relativistic rate and does not need a user correction.

## References

- [IS-GPS-200N, section 20.3.3.3.3.1](https://www.gps.gov/sites/default/files/2025-07/IS-GPS-200N.pdf)
- [Galileo OS SIS ICD v2.2, section 5.1.4](https://www.gsc-europa.eu/sites/default/files/sites/all/files/Galileo_OS_SIS_ICD_v2.2.pdf)
- Ashby (2003), *Relativity in the Global Positioning System*, Living
  Reviews in Relativity 6, 1.
