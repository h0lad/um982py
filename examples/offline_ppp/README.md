# Offline precise point positioning

Record raw UM982 observations at a stationary point, download precise IGS
products later, and process the occupation with CSSRlib's Python static PPP
solver. The result is an experimental float PPP estimate in the reference frame
of the selected products. The script does not resolve ambiguities or certify the
estimate's accuracy.

The steps below run from `lib/um982py` after [installing the package](../README.md#running-the-examples).
Install the optional Python PPP dependencies:

```bash
python -m pip install -r examples/offline_ppp/requirements.txt
```

This installs CSSRlib's development revision
`df0f26332498f1d581109f2ab1caffd68748e18c` directly from GitHub, so installation
requires Git. The revision is pinned because the development API can change.
CSSRlib implements the solver in Python and uses numerical packages including
NumPy, SciPy and Numba, which include native compiled components. You also need an internet connection for
product downloads and an ANTEX file with satellite and receiver calibrations.
See [CSSRlib](https://github.com/hirokawa/cssrlib) and
[IGS products](https://igs.org/products/). CSSRlib is based on RTKLIB code but
does not require RTKLIB to be installed or run.

## 1. Set up and record

Mount the antenna securely with a clear sky view and leave it still throughout
the occupation. Record the antenna model and radome, antenna serial number,
marker and antenna reference point (ARP), and the measured ARP offset from the
marker in metres. Use a calibrated antenna suitable for GPS L1 and L2, then
inspect the capture for gaps, cycle slips and multipath before interpreting the
result.

These recording times are rough planning guidance for a stationary antenna:

| Recording time | Purpose |
| --- | --- |
| 1–2 hours | Check the setup and obtain an initial estimate. |
| 4–6 hours | Collect a longer occupation for a first PPP analysis. |
| 12–24 hours | Start a serious static survey with more satellite geometry. |
| Multiple days | Compare independent occupations and investigate repeatability. |

Longer recording does not guarantee accuracy. Antenna calibration, sky view,
multipath, correction products and processing models all affect the result. The
current exporter also has unverified inter-signal phase alignment, as described
below. Compare results with an independently surveyed point before assigning an
accuracy.

Create a metadata JSON file using your actual antenna and measured offset. The
antenna type must match the 20-character model and radome field in the ANTEX
file. Replace every placeholder below, including the measured values. Use
`[0, 0, 0]` only if the ARP really coincides with the marker.

```json
{
  "antenna_type": "YOUR_MODEL      NONE",
  "antenna_number": "YOUR_SERIAL",
  "antenna_delta_hen": [0.0, 0.0, 0.0],
  "position_xyz": [0.0, 0.0, 0.0],
  "receiver_type": "UM982"
}
```

Replace `position_xyz` with an approximate marker position in geocentric ECEF
metres. A rough GNSS position is sufficient as a starting point, but zero is not
valid. The helper `um982py.geodesy.ecef_from_geodetic` converts approximate
latitude and longitude in degrees and ellipsoidal height in metres to ECEF.

```bash
python -m examples.offline_ppp record --port /dev/ttyUSB0 --baud 921600 \
  --duration 14400 --interval 5 --metadata station.json --output-dir occupation
```

This creates `capture.bin` with the original stream, `observation.obs` in RINEX
3.05, and `capture.json` with capture details, omissions and hashes. The recording
and its decoded observations are held in memory during export, so check memory
and storage before a long session. Keep the raw file and metadata for later
reprocessing. The receiver's actual signal configuration is not independently
verified by the export. Inspect the RINEX GPS observation types and check that
usable L1 and L2 code and carrier-phase observations are present. The exporter
omits an L2C component when its RINEX code is unverified. Only supply
`--l2c-code 2S`, `2L` or `2X` if you have independently established the correct
component. See the [RINEX export guide](../rinex_export/README.md).

To regenerate an observation file from the saved raw capture, use the exporter
with the same metadata and any independently established L2C setting:

```bash
python -m examples.rinex_export --replay occupation/capture.bin \
  --metadata station.json --output reprocessed.obs --json reprocessed.json
```

For long occupations, segment the recording to bound memory use and preserve
completed captures if the process stops. This mode requires POSIX file locking.

```bash
python -m examples.offline_ppp record --port /dev/ttyUSB0 --baud 921600 \
  --duration 86400 --interval 5 --segment-seconds 900 --metadata station.json \
  --output-dir occupation-segments
```

Each segment has its own raw capture, RINEX file and capture report. The session
journal records incomplete segments and hashes completed ones. Restart the same
command with `--resume` to continue without overwriting them. The recording
options and metadata must match the original session. Free disk space is checked before
each segment, with `--min-free-mib` controlling the threshold. Receiver
reconnection and export between segments can leave observation gaps, so the sum
of requested segment durations is not proof of continuous coverage.
The recorder fingerprints the receiver identity and configuration before and
after each segment and stops if either changes. Snapshots cannot rule out changes
between those checks. Transient connection failures are retried up to three times
with bounded exponential delays. Use `--max-retries`, `--retry-seconds` and
`--retry-max-seconds` to adjust the policy. Failed and incomplete segments remain
on disk for inspection.

To process completed segments as one GPS-only occupation:

```bash
python -m examples.offline_ppp merge --session occupation-segments \
  --output occupation-gps.obs
```

The merge verifies capture and RINEX hashes, retains GPS observables, and writes
an adjacent JSON provenance report. It rejects overlapping or out-of-order
epochs and differing station metadata. Carrier arcs are marked as interrupted
at segment boundaries because continuity has not been verified. Observations
from other constellations remain in the individual segment files.

## 2. Download products

```bash
python -m examples.offline_ppp download --observation occupation/observation.obs \
  --quality rapid --output-dir products
```

The script downloads matching CODE rapid SP3 orbits, CLK clocks, observable
signal biases and broadcast navigation files from BKG for the observation dates,
plus the preceding and following days for interpolation near day boundaries.
`--quality final` requests a matching final set, which may not be available for
every date in this archive. `--adjacent-days 0` restricts downloads to the
observation dates, which can reduce product coverage at their boundaries. Product
names in this example cover dates from 2022-11-27 onward. `products.json`
records the source URLs and SHA-256 hashes of the decompressed files.

Download an ANTEX calibration file separately. For example, the IGS provides
[igs20.atx](https://files.igs.org/pub/station/general/igs20.atx). Select a file
consistent with the orbit/clock product frame and with a valid calibration for
your actual antenna, radome, satellites and observation date. A model match does
not establish the validity of the calibration for a particular installation.

## 3. Solve offline

```bash
python -m examples.offline_ppp solve --observation occupation/observation.obs \
  --products products --antex igs20.atx --output-dir solution
```

Each output directory must be empty. The solve checks product hashes and that
the antenna type appears in ANTEX, then writes `solution.csv` and `report.json`.
The report includes the first and last PPP epochs, selected signals, accepted and
rejected epoch counts, satellites used, product provenance, input hashes and the
GPS phase-alignment declaration. A declaration is not independently verified.
The position uses geodetic latitude, longitude and ellipsoidal height. Interpret
it with the product reference frame and the marker/ARP convention. Times in the
report are GPS time.

The solver rejects orbit or clock products with missing epochs and skips
observations outside their coverage, allowing a one-second margin at the start
for signal transmission time. The report counts the skipped observations.
Supplying adjacent days improves coverage at midnight.

The solver uses GPS L1/L2 code, carrier phase and signal strength, precise
orbits and clocks, CODE signal biases, estimated ionosphere and troposphere,
antenna corrections, phase wind-up and an approximate solid Earth tide model.
It estimates float ambiguities and fixes the receiver position over the session.
It does not model ocean loading or pole tides. RINEX event epochs and carrier
phase LLI flags other than 0 or 1 are rejected because this CSSRlib revision does
not fully handle them. Inspect the capture and repeat occupations against an
independent surveyed point before assigning uncertainty or claiming accuracy.
An output position is not proof of convergence or measured error. Multipath,
phase slips, antenna calibration and atmospheric modelling can bias the result.

The UM982 exporter currently records inter-signal phase alignment as unknown.
Establish that alignment independently before using the exported phases for
precise work or publishing them as RINEX 3 observations. This example supports
the workflow but cannot establish centimetre-level accuracy from the data alone.

In a hardware test, RANGE and OBSVM carrier phases matched for 153 valid GPS
observations across ten shared epochs. The [hardware test](../../tests/hardware/test_extra_live.py) can repeat
this comparison and verifies receiver-state restoration. Both logs came from the
same receiver, so this result does not establish absolute phase alignment.
