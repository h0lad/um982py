# Offline precise point positioning

For relative post-processing with a base station, see the
[post-processed RTK example](../postprocessed_rtk/README.md).

Record raw UM982 observations with a stationary antenna. Then download precise
IGS products and process the recording with CSSRlib's Python static PPP solver.
The result is an experimental float PPP position in the products' reference
frame. The script does not resolve ambiguities or certify accuracy.

After [installing the package](../README.md#running-the-examples), run these
steps from the repository root. Install the optional Python PPP dependencies:

```bash
python -m pip install -r examples/offline_ppp/requirements.txt
```

Installation requires Git because it downloads CSSRlib revision
`df0f26332498f1d581109f2ab1caffd68748e18c` from GitHub. This revision is pinned
because the development API can change. The solver uses Python with numerical
packages such as NumPy, SciPy and Numba. These packages include compiled
components. CSSRlib is based on RTKLIB code and runs without an RTKLIB installation.

You also need internet access to download products and an ANTEX file with
satellite and receiver calibrations. See [CSSRlib](https://github.com/hirokawa/cssrlib)
and [IGS products](https://igs.org/products/).

## 1. Set up and record

Mount the antenna securely with a clear sky view and leave it still throughout
the occupation. Record the antenna model and radome, antenna serial number,
marker and antenna reference point (ARP), and the measured ARP offset from the
marker in metres. Use a calibrated antenna suitable for GPS L1 and L2. Before
interpreting the result, inspect the capture for gaps, cycle slips and multipath.

These recording times are rough planning guidance for a stationary antenna:

| Recording time | Purpose |
| --- | --- |
| 1–2 hours | Check the setup and obtain an initial estimate. |
| 4–6 hours | Collect a longer occupation for a first PPP analysis. |
| 12–24 hours | Record a static survey over a wider range of satellite geometry. |
| Multiple days | Compare independent occupations and investigate repeatability. |

The exporter does not verify phase alignment between signals. See the phase
alignment requirements in step 3 before using the phases for precise work.

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

To request a documented higher output rate, replace `--interval 5` with
`--rate-hz 10`. The receiver and signal group determine the actual cadence.
Recordings preserve native epochs without interpolation or gap filling.

This creates `capture.bin` with the original stream, `observation.obs` in RINEX
3.05, and `capture.json` with capture details, omissions and hashes. The
exporter holds the recording and decoded observations in memory, so check
memory and storage before a long session. Keep the raw file and metadata for
later reprocessing.

The export does not verify the receiver's signal configuration. Inspect the
RINEX GPS observation types for usable L1 and L2 code and carrier phase. The
exporter omits an L2C component if its RINEX code is unverified. Only supply
`--l2c-code 2S`, `2L` or `2X` if you have independently established the correct
component. See the [RINEX export guide](../rinex_export/README.md).

To regenerate an observation file, use the saved raw capture and the same
metadata. Include any independently established L2C setting:

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
options and metadata must match the original session. The recorder checks free
disk space before each segment. `--min-free-mib` controls the threshold.

Reconnection and export between segments can leave gaps in the observations.
The recorder compares fingerprints of the receiver identity and configuration
before and after each segment. It stops if either changes. Changes between
those checks may go undetected.

After a transient connection failure, the recorder retries up to three times
with bounded exponential delays. Adjust this policy with `--max-retries`,
`--retry-seconds` and `--retry-max-seconds`. Failed and incomplete segments stay
on disk for inspection.

To process completed segments as one GPS-only occupation:

```bash
python -m examples.offline_ppp merge --session occupation-segments \
  --output occupation-gps.obs
```

The merge checks capture and RINEX hashes, keeps GPS observables and writes a
JSON provenance report alongside the output. It rejects overlapping epochs,
epochs out of order and differing station metadata. Each segment boundary
marks an interruption in carrier arcs because continuity is unverified.
Observations from other constellations stay in the individual segment files.

## 2. Download products

```bash
python -m examples.offline_ppp download --observation occupation/observation.obs \
  --quality rapid --output-dir products
```

The script downloads matching CODE rapid SP3 orbits, CLK clocks, observable
signal biases and broadcast navigation files from BKG. It includes the days
before and after each observation date to support interpolation of products
near midnight.

`--quality final` requests a matching final set, which may not be available for
every date in this archive. `--adjacent-days 0` restricts downloads to the
observation dates, which can reduce product coverage at their boundaries. Product
names in this example cover dates from 2022-11-27 onward. `products.json`
records the source URLs and SHA-256 hashes of the decompressed files.

Download an ANTEX calibration file separately. For example, the IGS provides
[igs20.atx](https://files.igs.org/pub/station/general/igs20.atx). Select a file
that matches the orbit/clock product frame. It must include a valid calibration
for your antenna, radome, satellites and observation date. A model match does
not establish the validity of the calibration for a particular installation.

## 3. Solve offline

```bash
python -m examples.offline_ppp solve --observation occupation/observation.obs \
  --products products --antex igs20.atx --output-dir solution
```

Choose an empty output directory. Before solving, the script checks product
hashes and looks for the antenna type in ANTEX. It writes `solution.csv` and
`report.json`.

The report gives the first and last PPP epochs, selected signals, accepted and
rejected epoch counts and satellites used. It also records product provenance,
input hashes and the GPS phase-alignment declaration. Positions use geodetic
latitude, longitude and ellipsoidal height in the products' reference frame.
Check the marker/ARP convention when interpreting them. Reported times use GPS
time.

The CSV and report have no position uncertainty because the export does not
extract and validate the solver's covariance.

The solver rejects orbit or clock products with missing epochs and skips
observations outside their coverage, allowing a one-second margin at the start
for signal transmission time. The report counts the skipped observations.
Supplying adjacent days improves coverage at midnight.

The solver uses GPS L1/L2 code, carrier phase and signal strength with precise
orbits, clocks and CODE signal biases. It estimates ionosphere, troposphere and
float ambiguities while holding the receiver position constant over the session.
Antenna corrections, phase wind-up and an approximate solid Earth tide model
are included. Ocean loading and pole tides are not modelled.

This CSSRlib revision does not fully handle RINEX event epochs or carrier phase
LLI flags other than 0 or 1. The solver rejects them.

The UM982 exporter currently records inter-signal phase alignment as unknown.
Establish that alignment independently before using the exported phases for
precise work or publishing them as RINEX 3 observations.

In a hardware test, RANGE and OBSVM carrier phases matched for 153 valid GPS
observations across ten shared epochs. The [hardware test](../../tests/hardware/test_extra_live.py) can repeat
this comparison and verifies receiver-state restoration. Both logs came from the
same receiver.
