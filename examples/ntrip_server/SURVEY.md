# Station survey: from recording to caster

Mount the antenna, survey the marker, process it with PPP and write the station
manifest. Read the [quick start](README.md) first. Access control and operation
continue in [ACCESS.md](ACCESS.md) and [OPERATIONS.md](OPERATIONS.md).

Run the commands below from the `lib/um982py` project directory. Steps 1–3 use
the local receiver, while step 4 uploads the file to an online service. The final
station should use the reviewed result, not the rough receiver position. From
the outer workspace, run `cd lib/um982py` first and follow the
[installation instructions](../README.md#running-the-examples).

## 1. Install the antenna and record its details

Mount the primary antenna permanently with a clear view of the sky and as little
signal reflection from nearby roofs, walls and metal as possible. Use a
calibrated multi-frequency antenna and record the
exact IGS antenna/radome code. Measure the vertical distance from the marked
point to the antenna reference point (ARP) and any horizontal eccentricity:
H/E/N in metres. Convert a slanted tape measurement first.

Write down these details before recording:

- Marker name and the antenna and receiver serial numbers.
- Exact IGS antenna/radome code, if known.
- Height, east and north offsets from the marker to the antenna reference point
  (ARP), in metres. The ARP is the manufacturer's stated mechanical reference
  point, often the bottom of the antenna mount, so check its documentation. It is
  not the antenna's electrical phase centre.

### What `--antenna-hen H E N` means

Choose a permanent, identifiable **marker**, for example a bolt or marked
point on a rigid mounting plate. The three numbers describe the position of the
antenna's ARP **relative to that marker**, in this exact order, in metres:

| Value | Measurement | Sign |
| --- | --- | --- |
| `H` | Vertical height from the marker up to the ARP, not a sloping tape measurement. | Non-negative, within the accepted range of 0–100 m. |
| `E` | Horizontal offset from the marker to the ARP in the east direction. | East is positive, west is negative. |
| `N` | Horizontal offset from the marker to the ARP in the north direction. | North is positive, south is negative. |

For example, `--antenna-hen 1.2345 0.0000 0.0000` describes an ARP **1.2345 m
above** the marker, directly above it, with no east or north displacement.
It does **not** mean the antenna is 1.2345 m above sea level, and `1.2345` is
not a suitable default: measure your own installation. If the ARP is 1.20 m
above, 0.02 m west, and 0.03 m north of the marker, enter
`--antenna-hen 1.20 -0.02 0.03`. If the marker is the ARP itself, enter
`--antenna-hen 0 0 0`.

Use a level or other appropriate method for vertical height. If you measure a
slanted distance, convert it to a vertical height using the antenna's specified
measurement geometry rather than entering the slant length as H. Record the measurement
method and check the antenna manufacturer's reference-point definition. If the
mounting arrangement or offsets are uncertain, resolve that before accepting a
precise solution.

## 2. Obtain a rough position

A rough position for the RINEX header comes from:

```bash
python -m examples.base_station_survey --port /dev/ttyUSB0 --baud 921600 --json rough-position.json
```

The command prints latitude, longitude, ellipsoidal height and ECEF X/Y/Z, and
saves them in `rough-position.json`. This average does not establish absolute
centimetre accuracy, even when it says `converged`. The next step uses ECEF as
an approximate RINEX header position, not as the final base position. The
`--approx-position` option expects approximate **marker** ECEF in metres. If
the antenna-to-marker offset is large, account for it in the approximation.

## 3. Record and export 24 hours of observations

Keep the receiver, antenna and computer running without moving the antenna.
The following command uses the rough ECEF from step 2. Replace the antenna and
receiver identifiers and H/E/N offsets with your own values. The `read` line
uses Bash, the shell used by the examples below:

```bash
read -r survey_x survey_y survey_z < <(python -c 'import json; print(*json.load(open("rough-position.json"))["ecef"])')
python -m examples.ntrip_server \
  --port /dev/ttyUSB0 --baud 921600 \
  --survey-output BASE01.rnx --record BASE01-wire.bin \
  --seconds 86400 --interval 30 --marker-name BASE01 \
  --antenna-type 'YOUR_ANTENNA   NONE' --antenna-serial ANT123 \
  --receiver-serial RX123 --receiver-firmware YOUR_BUILD \
  --approx-position "$survey_x" "$survey_y" "$survey_z" \
  --antenna-hen 1.2345 0.0000 0.0000
```

The options in this command mean:

| Option | What to supply or expect |
| --- | --- |
| `--port` / `--baud` | The receiver's serial device and baud rate. Only one program can use the device at a time. |
| `--survey-output BASE01.rnx` | A new output filename for the observation file submitted to CSRS-PPP. The RINEX file is exported after recording. |
| `--record BASE01-wire.bin` | A new filename for the raw receiver data, useful if export must be retried. |
| `--seconds 86400 --interval 30` | Record for up to 24 hours, requesting one observation epoch every 30 seconds. Confirm the actual epoch count and gaps afterward. |
| `--marker-name BASE01` | A short name you choose for the surveyed fixed point. |
| `--antenna-type` | The actual antenna and radome code in IGS format, if known. A radome is a protective cover, and `NONE` means no radome. |
| `--antenna-serial`, `--receiver-serial`, `--receiver-firmware` | The actual identifiers from the equipment or its configuration, up to 20 ASCII characters each. |
| `--approx-position` | Approximate marker X/Y/Z in metres, here taken from step 2. It is a starting value, not the surveyed solution. |
| `--antenna-hen` | Your measured marker-to-ARP offsets in height/east/north order, in metres, as explained in step 1. |

The antenna, receiver and offset values shown in the command are placeholders,
not measurements. Replace them before running it. Repeat the full observation
on an independent day and compare the two solutions before accepting the
position. Use different output filenames for the second session.

`--antenna-type` holds the exactly formatted IGS antenna/radome code (20
characters maximum). Set H/E/N to zero only when the ARP itself is the marker.
The library writes H/E/N into the RINEX file so the PPP service can relate the
antenna and marker. These offsets are not an antenna phase-centre correction.
Enter the measured values in the same H/E/N order shown above.
Capture and export use `FirmwareLog.RANGE` on ANT1 and
`um982py.rinex.export_rinex()` for RINEX 3.05. Supported simultaneous code/phase
pairs on GPS L1/L2 or Galileo E1/E5a are required. GPS L1/L5 alone does not pass
this export check. Set `--l2c-code` only for a known firmware relationship, and
omitted observations are reported.

Epochs stay in RAM until export, while `--record` preserves the raw data. Limits: 48 h,
interval at least 15 s. Watch memory and free disk space. After an interruption,
check the reported epoch count. To recover, rerun the same invocation with
`--replay BASE01-wire.bin` instead of `--port`, omit `--record`, and use a new
`--survey-output` filename.
Check frequencies, data gaps and cycle slips before uploading.

## 4. Submit the observation file to CSRS-PPP

1. Open Canada's [CSRS-PPP service](https://webapp.csrs-scrs.nrcan-rncan.gc.ca/geod/tools-outils/ppp.php?locale=en).
   Sign in or register if requested. Recording is local, while submission and
   processing happen online.
2. Submit `BASE01.rnx`, choose **Static**, and select the reference frame
   appropriate for the rover project (for Germany this may be an ITRF
   realization). Check the antenna model and metadata shown by the service.
3. Download the result and summary report. Check the solution status,
   uncertainties, antenna handling, point reference, frame and coordinate
   epoch. If the antenna is uncalibrated or unsupported, investigate the
   report's warnings and their effect on accuracy before accepting it.
4. For a definitive result, wait for final orbit and clock products, resubmit
   if needed, and confirm the report actually used them. NRCan says final
   products are typically available 12–15 days after the end of the week, so see
   [CSRS-PPP information](https://webapp.csrs-scrs.nrcan-rncan.gc.ca/geod/tools-outils/ppp-info.php?locale=en)
   for current availability. Compare the independent second day's solution,
   and keep the RINEX, raw recording, field notes and reports.

The report must identify whether the coordinates refer to the marker or ARP,
as well as their frame realization and coordinate epoch. If any of those are
unclear, resolve them before entering coordinates rather than assuming the
observation date is the coordinate epoch. The library does not run CSRS-PPP or
verify the external solution's absolute accuracy.
Do not apply the marker-to-ARP offsets again if the coordinates in the report
already refer to the ARP. If the report gives marker coordinates, use the
offsets once in the next step because the presence of H/E/N in the RINEX header alone
does not tell you which point a particular report labels as its result.

## 5. Convert marker coordinates to ARP if needed

The server expects **ARP latitude, ARP longitude and ellipsoidal ARP height** in
degree/degree/metre. Do not use an orthometric height. The ARP is forwarded to
the receiver in ECEF form: a geodetic `MODE BASE` altitude is converted through
the receiver's geoid model, which would move RTCM 1005 by the local undulation
(about 49 m in Central Europe) and fail the 2 cm manifest check. If PPP returns
the marker, transfer the measured H/E/N with our coordinate example:

```python
from examples.coordinate_frames import Baseline, Geodetic, antenna_position

marker = Geodetic(latitude=50.0, longitude=8.0, height=122.1655)
arp = antenna_position(marker, Baseline(east=0.0, north=0.0, up=1.2345))
print(arp.latitude, arp.longitude, arp.height)
```

Alternatively, the setup wizard in step 6 performs this conversion when you
select `marker` and supply the measured offsets. If your report gives ECEF
X/Y/Z rather than latitude, longitude and height, convert the **same point**
first, replacing the example numbers with the report's actual coordinates:

```python
from examples.coordinate_frames import Geodetic

point = Geodetic.from_ecef(4060000.0, 571000.0, 4880000.0)  # example only
print(point.latitude, point.longitude, point.height)
```

Enter the resulting values as `marker` or `arp` according to the report. These
conversions do not change the reference frame or coordinate epoch.

Do not add phase-centre offsets that are already modelled. Reference frame and
coordinate epoch must match the rover project because the library neither transforms
nor propagates them. Survey again after changing the antenna.

## 6. Enter the reviewed position and start the caster

Run the guided setup:

```bash
python -m examples.ntrip_server.setup
```

Select `arp` if the reviewed coordinates are already the antenna reference
point, or `marker` if they refer to the surveyed ground marker. Enter decimal
degrees (north/east positive), **ellipsoidal** height in metres, and the
reference frame and decimal-year coordinate epoch from the report. If you
select `marker`, enter your measured up/east/north offsets, and the wizard prints
the calculated ARP before asking you to confirm the review. It then creates
`ntrip-station/start.sh` and the necessary station and account files.

```bash
./ntrip-station/start.sh
```

For manual configuration instead:

```bash
cp examples/ntrip_server/station.example.json station.json
```

Enter the ARP coordinates, `reference_frame`, `coordinate_epoch` and
`source_report`. Choose a unique station ID and mountpoint. Set
`position_verified` to `true` only after review. The server will not start with
the template's unverified position. It sets the receiver antenna offset to zero,
validates every station ID and compares RTCM 1005 coordinates against the
manifest (2 cm tolerance).

Continue with [access and TLS](ACCESS.md).
