# Measure snow or water with GNSS reflectometry

A fixed GNSS antenna receives signals directly and as reflections from nearby
surfaces. As a satellite rises or sets, the combined signal strength changes.
This example uses that pattern to estimate the **reflector height**: the
vertical distance from the antenna to an effective reflecting surface.

Use the height to estimate either snow depth or water level:

- For snow, compare it with the measured snow-free antenna-to-ground height.
  As snow accumulates, the reflector height becomes smaller.
- For water, subtract it from the surveyed antenna elevation to estimate the
  water level in that elevation's vertical datum.

The model assumes a fixed antenna above an approximately horizontal surface.

## What you need

- A UM982, a supported antenna with a clear view of the sky and a computer
  running Python 3.12 or later. One antenna is enough for the workflows below.
- A stable mount and an open reflecting area in the satellite directions you
  plan to analyze. Buildings, vegetation and other surfaces can also reflect
  signals. The reflecting area is not necessarily directly below the antenna.
- For snow, a measured snow-free antenna-to-ground height and a way to record
  snow depths independently, such as a snow stake.
- For water, the antenna elevation relative to a known vertical datum. A gauge
  in that same datum is strongly recommended for validation.

The effective antenna phase centre may differ from the physical point used for
a tape or survey measurement. Record how you measured the height and use the
same antenna reference throughout.

Run the commands from the repository root after following the
[installation instructions](../README.md#running-the-examples). Choose paths for
your data and replace `/dev/ttyUSB0` if your receiver uses another port.

## 1. Record and estimate reflector heights

For a single antenna on ANT1, this command records one hour of observations,
saves a replayable wire capture, and writes an arc CSV and JSON report:

```bash
mkdir -p captures
python -m examples.gnss_reflectometry --port /dev/ttyUSB0 --baud 921600 \
    --single-antenna --antenna primary --duration 3600 --interval 5 \
    --min-height 1 --max-height 6 --record captures/day1.bin \
    --csv day1-arcs.csv --json day1-report.json --debug
```

`--min-height` and `--max-height` bound the antenna-to-reflector distance in
metres, not snow depth or water level. Choose bounds for your site that cover
the distance throughout the experiment. Use a new capture filename for each
session. The program will not overwrite an existing file.

The program records RANGE observations and SATVIS2 satellite geometry. It
groups observations into satellite arcs and screens them for sufficient data and
a usable spectral peak. The two primary outputs are:

| Output | Use |
| --- | --- |
| `day1-arcs.csv` | One row per arc, including antenna, GPS times, `height_m` and `rejection`. This is the input to the snow and water commands below. |
| `day1-report.json` | Capture settings, counts, quality information and detailed arc results. Keep it with the raw capture and field notes. |

An empty `rejection` field means the arc passed the configured checks. Rejected
arcs include a reason. Do not use them as height estimates. If no heights are
accepted, the program writes its report and exits with a nonzero status.

The report counts distinct constellation, satellite and pass direction
combinations in `automatic_height.distinct_tracks` and
`observed_sectors[].accepted_distinct_tracks`. Frequencies from the same track
count once, and passes with the same satellite and direction are grouped.
Different tracks can still share environmental and model errors.

Use new filenames such as `captures/day2.bin`, `day2-arcs.csv` and
`day2-report.json` for another recording.

To reprocess a recorded capture without connecting to the receiver, use:

```bash
python -m examples.gnss_reflectometry --replay captures/day1.bin \
    --single-antenna --antenna primary --interval 5 \
    --min-height 1 --max-height 6 --csv day1-reprocessed.csv \
    --json day1-reprocessed.json --debug
```

Replay needs the relevant RANGE and SATVIS2 records. Set `--interval` to the
capture cadence: the default arc-gap limit is three times this value. Replay
does not create missing measurements or resample them.

## Identify the possible reflecting surface

For each satellite arc, the horizontal-surface model estimates where a
reflection could originate. The receiver cannot identify the surface as snow,
water or ground. Compare the modeled area with a current aerial image, site map
and field observations before assigning a surface type.

For a horizontal reflector, the modeled specular point is on the same side of
the antenna as the satellite. Its approximate horizontal distance is:

```text
distance = antenna-to-surface height / tan(satellite elevation)
```

For an antenna 2 m above the surface, the point is roughly 23 m away at 5°
elevation, 11 m at 10° and 3.5 m at 30°. An area around that point affects the
signal. The size and shape of the modeled first Fresnel zone depend on signal
frequency and change as the satellite moves.
[PSMSL's footprint viewer](https://psmsl.org/data/gnssir/seaviewer.php) can
help visualize approximate zones on a map.

Map the antenna position and the surrounding snow, water, land and structures.
If the sea lies to the southeast, for example, you can reprocess a capture
using satellite azimuths from 90° to 180°:

```bash
python -m examples.gnss_reflectometry --replay captures/day1.bin \
    --single-antenna --antenna primary --interval 5 \
    --azimuth-start 90 --azimuth-end 180 \
    --csv water-sector-arcs.csv --json water-sector-report.json
```

Azimuth is clockwise from geographic north: north is 0°, east 90°, south 180°
and west 270°.
Use separate sector outputs for snow and water when their reflecting areas are
in different directions. An azimuth filter selects satellite directions, but it
does not guarantee that the whole reflection area stays within that sector or
over one material.

The detailed JSON report has an `arcs` list under `antennas` for `ANT1` and
`ANT2`. Each arc contains `azimuth_mean_deg`, elevation limits, `rejection`
and a `footprint` when a height is available. The footprint contains:

- `start`, `middle` and `end`: modeled specular-point coordinates, Fresnel
  ellipse centre and semiaxes for those three samples.
- `fresnel_bounds_m`: a bounding rectangle covering the modeled ellipses over
  the arc. It is not the boundary of one measured reflector.
- `reference_height_m`: the antenna-to-surface height used in the model.
  The arc's `footprint_height_source` says whether it came from a supplied
  reference height or the spectral estimate.

Coordinates are local metres east and north of the antenna. The arc CSV has
the height and rejection information, but not the full footprint geometry. To
print the middle sample of each accepted ANT1 arc:

```bash
python - <<'PY'
import json

with open("water-sector-report.json", encoding="utf-8") as stream:
    report = json.load(stream)

for arc in report["antennas"]["ANT1"]["arcs"]:
    if arc["rejection"] is not None or arc["footprint"] is None:
        continue
    middle = arc["footprint"]["middle"]
    print(
        arc["constellation"], arc["prn"], arc["signal_name"],
        "azimuth:", arc["azimuth_mean_deg"],
        "specular east/north (m):",
        middle["specular_east_m"], middle["specular_north_m"],
        "Fresnel semimajor/semiminor (m):",
        middle["fresnel_semimajor_m"], middle["fresnel_semiminor_m"],
        "height source:", arc["footprint_height_source"],
    )
PY
```

These footprints are geometric estimates. If a footprint covers a mix of snow,
water, land or structures, the source of the reflection is ambiguous. Moving
shorelines, changing water levels, slopes, waves and snow layering can violate
or complicate the model. Changes in antenna-to-surface height also affect it. Reject or
investigate ambiguous arcs and compare the selected area with independent field
measurements.

## 2a. Estimate snow-depth change

Measure the snow-free distance from the antenna reference to the ground before
snow accumulates. Keep the antenna fixed and record the measurement, reference
point, site and date. Export an arc CSV for each later session using step 1.

For example, if the snow-free height is **2.5 m** and an accepted arc gives a
reflector height of **2.1 m**, the reported snow-height proxy is **0.4 m**:

```text
snow-height proxy = snow-free antenna-to-ground height − reflector height
```

Replace `2.5` with your own measured baseline:

```bash
python -m examples.gnss_reflectometry.snow_series \
    --arcs day1-arcs.csv day2-arcs.csv --antenna ANT1 \
    --baseline-height-m 2.5 --output snow.json
```

The JSON contains `accepted_arcs` with their `snow_height_proxy_m` values and a
separate `rejected_arcs` list. Negative proxies are retained for review.
`height_resolution_m` describes spectral resolution, not measurement uncertainty.

To compare with field observations, add `--field snow-stake.csv` and choose a
`--field-window-s` appropriate for your experiment. The CSV must have these
columns, with your own times and non-negative depths in metres:

```csv
gps_seconds,snow_depth_m
1450000300,0.35
1450000900,0.48
```

The program matches the closest field reading to each arc midpoint within the
specified window, which defaults to 3600 seconds. Choose a window suited to
how quickly conditions change. Unmatched observations have no field comparison.
Multiple arcs can reuse a reading, and a point measurement may not represent
the whole reflecting area.

## 2b. Estimate water level

Establish the antenna elevation in metres relative to a named vertical datum.
If using a gauge, its water levels must use the **same datum**. Record the
survey method and antenna reference point.

For example, an antenna elevation of **4.2 m** and a reflector height of
**2.1 m** give an estimated water level of **2.1 m** in that datum:

```text
water level = antenna elevation in datum − reflector height
```

Replace the example elevation and datum with your surveyed values:

```bash
python -m examples.gnss_reflectometry.water_level \
    --arcs day1-arcs.csv day2-arcs.csv --antenna ANT1 \
    --antenna-elevation-m 4.2 --datum 'your vertical datum' \
    --output water.json
```

To compare with a gauge, add `--gauge gauge.csv` and an explicit
`--match-window-s` in seconds. The CSV uses the same GPS time scale as the arc
file and the same height datum as the antenna:

```csv
gps_seconds,water_level_m
1450000300,2.00
1450000900,2.15
```

```bash
python -m examples.gnss_reflectometry.water_level \
    --arcs day1-arcs.csv day2-arcs.csv --antenna ANT1 \
    --antenna-elevation-m 4.2 --datum 'your vertical datum' \
    --gauge gauge.csv --match-window-s 60 --output water-with-gauge.json
```

The matching window limits the time between an arc midpoint and a gauge reading.
Choose it for the rate of water-level change and the gauge cadence. The example
uses 60 seconds. The report lists time offsets, counts of matched and reused
gauge values, residuals and rejected arcs.

Reused gauge values and arcs with similar geometry cannot count as independent
measurements. The report applies no correction for tides during an arc, waves,
vertical land motion or differences between the gauge and reflecting area.

Add `--plot water.png` to create a water-level and residual figure. Plotting
requires a separate `matplotlib` installation.

## Try both workflows without hardware

The files in `examples/gnss_reflectometry/data/` contain **synthetic values**
for learning the output format. From the repository root, run:

```bash
python -m examples.gnss_reflectometry.snow_series \
    --arcs examples/gnss_reflectometry/data/synthetic_arcs.csv --antenna ANT1 \
    --baseline-height-m 2.5 \
    --field examples/gnss_reflectometry/data/synthetic_snow_field.csv \
    --field-window-s 60 --output /tmp/synthetic-snow.json

python -m examples.gnss_reflectometry.water_level \
    --arcs examples/gnss_reflectometry/data/synthetic_arcs.csv --antenna ANT1 \
    --antenna-elevation-m 4.2 --datum 'synthetic datum' \
    --gauge examples/gnss_reflectometry/data/synthetic_water_gauge.csv \
    --match-window-s 60 --output /tmp/synthetic-water.json
```

For the first accepted arc, the snow proxy is 0.4 m and the water-level estimate
is 2.1 m. Both reports retain one deliberately rejected arc.

## Times, quality checks and troubleshooting

- `gps_seconds` is continuous GPS time in seconds since the GPS epoch
  (1980-01-06), not a Unix timestamp or a UTC date string. Use GPS week ×
  604800 plus GPS seconds of week, or convert UTC using verified leap-second
  information. Do not assume the GPS–UTC offset is always constant.
- `no_synchronized_samples` means the report found no usable joined
  observations and satellite geometry. Check that the capture contains RANGE
  and SATVIS2 for the selected antenna and times.
- `insufficient_arc` means samples were present but no arc passed all checks.
  Inspect `rejection` in the CSV and `rejection_counts` in the JSON, then check
  site geometry, capture length, cadence and height search bounds. Do not lower
  thresholds just to obtain a result without documenting the reason.
- `height_at_search_boundary` means the peak landed at a search limit. Review
  the site's plausible reflector heights and the chosen bounds.
- The same antenna, surface area, geometry and processing choices matter when
  comparing sessions. Record site conditions and compare results with
  independent snow or water measurements. A reported RMS difference is not a
  complete uncertainty budget.

## Advanced options

Use `--samples-csv` to save joined observations, `--spectra-csv` to save
periodograms, and `--rinex-dir` for observation exports. Omit
`--single-antenna` to process both inputs when both are connected. The
`--azimuth-start` and `--azimuth-end` options restrict the sky sector. Review
which surface each satellite geometry can actually reflect from.

For phase comparisons between captures, supply `--reference-json` and measured
`--reference-height-ant1` and/or `--reference-height-ant2`. Phase comparisons
require matched geometry and measured heights. Refraction and surface dynamics
are not corrected. Run `python -m examples.gnss_reflectometry --help` for the
full set of filters and thresholds.

## References

[Roesler & Larson (2018)](https://doi.org/10.1007/s10291-018-0744-8),
[GNSS-IR processing](https://gnssrefl.readthedocs.io/en/latest/pages/gnssir.html),
[first Fresnel geometry](https://www.mdpi.com/2076-3263/11/9/391).
