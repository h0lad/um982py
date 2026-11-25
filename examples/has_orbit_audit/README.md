# Galileo HAS orbit and clock audit

Measure how much the Galileo High Accuracy Service improves the broadcast
GPS and Galileo orbits and clocks. The audit applies the receiver-decoded
E6-B HAS corrections to the broadcast ephemerides they reference. It then
scores both the plain broadcast state and the HAS-corrected state against
an IGS precise product (SP3), reporting the signal-in-space range error
(SISRE) per constellation and per satellite.

## Run

Run from the repository root after [installation](../README.md#running-the-examples).

Record about a day of corrections and ephemerides. Connect the broadband
antenna to ANT1 and let `--augment` enable E6-HAS tracking:

```bash
python -m examples.has_orbit_audit --port /dev/ttyUSB0 --baud 921600 --augment \
    --duration 86400 --record captures/has-day.bin \
    --sp3 products/COD0MGXFIN.sp3 --json has-audit.json
```

Re-score the recording against another product, for example a final
product published about two weeks later:

```bash
python -m examples.has_orbit_audit --replay captures/has-day.bin \
    --sp3 products/COD0MGXFIN.sp3 --systems E --pco-z 0.8 --json has-audit.json
```

## Inputs and results

The SP3 product must use GPS time and cover the recording. Multi-GNSS
products from the IGS MGEX analysis centres include Galileo. Predicted
epochs and epochs without a precise clock are skipped.

For every SP3 epoch, the audit selects the latest HAS clock block whose
orbit and clock validity intervals both cover that epoch. It then finds the
broadcast ephemeris whose issue matches the correction's `IODref`: IODnav
for Galileo and IODE for GPS. Orbit corrections are rotated from the
radial, in-track and cross-track frame of the broadcast ECEF state and
added to it, and clock corrections are added to the ionosphere-free
broadcast clock with its relativistic term (HAS SIS ICD, section 7, Eq.
18-23). Galileo uses the I/NAV clock, the reference message of HAS.

`sisre_m` lists, per system, the RMS and maximum SISRE of the broadcast
and HAS-corrected states. `satellites` gives the same per satellite, and
`skipped` counts why epochs could not be compared.

## Understanding the result

HAS corrections refer to the satellite's ionosphere-free antenna phase
centre, while SP3 positions refer to the centre of mass. `--pco-z` moves
the reference towards the Earth by the nadir phase-centre offset. Take the
value for the satellites' ionosphere-free signal pair from the IGS ANTEX
file. A single value applies to all satellites, and horizontal offsets are
ignored.

Each epoch's median clock difference is removed per system, because the
precise product uses its own clock datum. At least four satellites of a
system must be compared at an epoch. Galileo products from IGS use
E1/E5a clocks, while HAS corrects the E1/E5b I/NAV clock. The resulting
group-delay difference remains in the score of both services.

The SISRE weights are 0.98 radial with 1/49 (GPS) or 1/61 (Galileo) for the
squared along-track and cross-track errors.

## References

- [Galileo HAS SIS ICD, Issue 1.0, sections 5.2 and 7](https://www.gsc-europa.eu/sites/default/files/sites/all/files/Galileo_HAS_SIS_ICD_v1.0.pdf)
- Montenbruck, Steigenberger & Hauschild (2018), *Multi-GNSS signal-in-space
  range error assessment - Methodology and results*, Advances in Space
  Research 61(12), 3020-3038.
- Hilla (2010), SP3-c.
