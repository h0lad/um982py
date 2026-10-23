# Measure snow or water with GNSS reflectometry

A fixed GNSS antenna receives satellite signals directly and after reflection
from a nearby surface. As a satellite rises or sets, the combined signal
strength changes. This example looks for that pattern and estimates the
vertical distance from the antenna to the reflecting surface, called the
**reflector height**.

Use the estimated height in two ways:

- **Snow:** compare it with a measured snow-free antenna-to-ground height.
  If the reflecting surface rises as snow accumulates, the estimated reflector
  height becomes smaller.
- **Water:** subtract it from the surveyed antenna elevation in a specified
  vertical datum to estimate water level in that datum.

These are estimates of an effective reflecting surface, not direct depth or
water-level measurements. The method assumes a fixed antenna and an
approximately horizontal surface. Site geometry, snow properties, waves,
other reflecting objects and signal quality can affect the result. Validate
against independent measurements before using the estimates for research.

## What you need

- A UM982, a supported antenna with a clear view of the sky and a computer
  running Python 3.12 or later. One antenna is enough for the workflows below.
- A stable mounting position and a sufficiently open reflecting area in the
  satellite directions you will analyze. Nearby buildings, vegetation or other
  surfaces can contribute reflections. The relevant area is not necessarily
  directly below the antenna.
- For snow, a measured snow-free antenna-to-ground height and a way to record
  snow depths independently, such as a snow stake.
- For water, the antenna elevation relative to a known vertical datum. A gauge
  in that same datum is strongly recommended for validation.

The effective GNSS antenna phase centre and the physical point used for a tape
or survey measurement may differ. Record how the height was established and
use a consistent antenna reference. Do not assume a hardware calibration or
position accuracy that you have not established.

Run the commands from `lib/um982py` in a source checkout after following the
[installation instructions](../README.md#running-the-examples). Choose paths
for your data and replace `/dev/ttyUSB0` if your receiver uses another port.

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

`--min-height` and `--max-height` define the search range in metres, not the
expected snow depth or water level. Choose a range that covers the possible
**antenna-to-reflector distance** throughout your experiment. The values above
are examples and may not suit your site. Use a new capture filename for each
session because the program will not overwrite an existing file.

The program records RANGE observations and SATVIS2 satellite geometry, groups
observations into satellite arcs, then screens those arcs for sufficient data
and a usable spectral peak. The two primary outputs are:

| Output | Use |
| --- | --- |
| `day1-arcs.csv` | One row per arc, including antenna, GPS times, `height_m` and `rejection`. This is the input to the snow and water commands below. |
| `day1-report.json` | Capture settings, counts, quality information and detailed arc results. Keep it with the raw capture and field notes. |

An empty `rejection` field means the arc passed the configured checks. A
rejected arc has a reason and should not be treated as a height estimate. A
passing arc is still not independently validated. If no heights are accepted,
the program writes its report and exits with a nonzero status.

The report counts distinct combinations of constellation, satellite and pass
direction in `automatic_height.distinct_tracks` and
`observed_sectors[].accepted_distinct_tracks`. These counts do not establish
statistical independence: different tracks can share environmental and model
errors. Multiple frequencies of the same track count once, and passes with the
same satellite and direction are grouped together.

Repeat the recording at the same site as needed, using new filenames such as
`captures/day2.bin`, `day2-arcs.csv` and `day2-report.json`. A longer capture
may include more useful arcs, but there is no guarantee that every session will
produce one.

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

The receiver does not label a reflection as snow, water or ground. For each
satellite arc, the report estimates where a reflection *could* come from under
the horizontal-surface model. Compare that modeled area with a current aerial
image, site map and field observations before assigning it to a surface.

For a horizontal reflector, the modeled specular point is on the same side of
the antenna as the satellite. Its approximate horizontal distance is:

```text
distance = antenna-to-surface height / tan(satellite elevation)
```

For an antenna 2 m above the surface, the point is roughly 23 m away at 5°
elevation, 11 m at 10° and 3.5 m at 30°. The signal is affected by an area
around that point, not just one point. The size and shape of the modeled first
Fresnel zone also depend on the signal frequency and change as the satellite
moves. [PSMSL's footprint viewer](https://psmsl.org/data/gnssir/seaviewer.php)
can help visualize approximate zones on a map.

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
and west 270°. The example sector is only appropriate if it matches your site.
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

These footprints are geometric estimates, not proof of the actual reflection
path. Mixed snow, water, land and structures within a footprint make attribution
ambiguous. Shorelines and water levels can move, and slopes, waves, snow
layering and changing antenna-to-surface height violate or complicate the simple
model. Reject or investigate ambiguous arcs and compare the selected area with
independent field measurements.

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

The JSON contains `accepted_arcs`, their `snow_height_proxy_m` values and a
separate `rejected_arcs` list. Negative proxies are retained for review rather
than forced to zero. `height_resolution_m` describes spectral resolution, not
measurement uncertainty.

To compare with field observations, add `--field snow-stake.csv` and choose a
`--field-window-s` appropriate for your experiment. The CSV must have these
columns, with your own times and non-negative depths in metres:

```csv
gps_seconds,snow_depth_m
1450000300,0.35
1450000900,0.48
```

The closest field reading is matched to the midpoint of each arc within the
specified window. The default window is 3600 seconds, so select a smaller or
larger value deliberately if conditions change on a different timescale.
Unmatched observations remain without a field comparison. A field reading can
be reused by multiple arcs, and a point measurement may not represent the
whole reflecting area.

Snow density, layering, surface conditions and the ground beneath can affect
the effective reflection. Treat the output as a proxy until you have compared
it with independent, spatially representative snow measurements.

## 2b. Estimate water level

Establish the antenna elevation in metres relative to a named vertical datum.
If using a gauge, its water levels must use the **same datum**. Record the
survey method and antenna reference point, which the tool cannot verify.

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

The matching window is a maximum difference between an arc midpoint and a
gauge timestamp. Choose it for the changing water level and gauge cadence. The
60 seconds above is an example, not a universal limit. The report includes each
time offset, matched and reused gauge counts, residuals, and rejected arcs. A
reused gauge value or several arcs from similar geometry are not independent
measurements. The report does not correct tides during an arc, waves, vertical
land motion or differences between the gauge and reflecting area.

Add `--plot water.png` to create a water-level and residual figure. Plotting
requires a separate `matplotlib` installation.

## Try both workflows without hardware

The files in `examples/gnss_reflectometry/data/` contain **synthetic values**
for learning the output format. They are not measurements and do not validate
the reflector-height algorithm. From `lib/um982py`, run:

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

For the first accepted arc, the snow proxy is 0.4 m and the water-level
estimate is 2.1 m. Both reports also retain one deliberately rejected arc. The
same synthetic arc heights demonstrate both calculations. They do not represent
a single site with both snow and water.

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
  the site's plausible reflector heights and the chosen bounds. A wider search
  does not by itself establish that a peak is physical.
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
