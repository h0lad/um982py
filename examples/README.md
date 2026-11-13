# Examples

Run these examples to read receiver data and analyze GNSS measurements.

Run live examples through a local serial device or a transparent UART gateway
specified as `--port tcp://host:port`. Configure the gateway's UART baud
rate separately, since `--baud` applies only to local serial devices.

## Choose a starting point

| What you want to do | Example |
| --- | --- |
| Follow a position and detect stale fixes | [Live position](live_position/README.md) |
| Map receiver-reported position uncertainty | [Position precision](position_precision/README.md) |
| Use RTK corrections on a rover | [NTRIP rover](ntrip_client/README.md) |
| Survey a stationary point | [Static occupation](precise_fix/README.md) |
| Review motion on land, at sea or in the air | [Journey tracking](journey_track/README.md) |
| Record observations for research | [Research session](research_session/README.md) |
| Export observations for post-processing | [RINEX export](rinex_export/README.md) |
| Set up a reference station | [NTRIP reference station](ntrip_server/README.md) |
| Investigate reception and interference | [Signal quality](signal_quality_report/README.md) and [interference monitor](interference_monitor/README.md) |
| Inspect receiver time and PPS | [Time transfer](time_transfer/README.md) |

## Running the examples

From the repository root, install the package:

```bash
python -m pip install .
```

Examples run from the source checkout and are included in the source
distribution. The installed wheel contains the library and CLI, not the
`examples` package.

Choose an example below and use `--help` to see its options:

```bash
python -m examples.position_tracking --help
```

Replace `/dev/ttyUSB0` with your receiver's serial device. Many examples accept
`--replay` to read a capture without hardware and `--record` to save live data.
The recording destination must not already exist. Paths such as `captures/` and
`products/` are placeholders. Supply your own files and create the directories
as needed. The repository includes the files under `tests/fixtures/`.

For periodic receiver logs, `--interval` sets the requested interval in seconds.
Capture preserves native receiver epochs without interpolation or duplicated
measurements. Check timestamp spacing for the actual rate and gaps. If the
receiver repeats a timestamp, count it as the same epoch.

Some capture examples also accept a documented N4 rate in Hz through
`--rate-hz`:

```bash
python -m examples.position_tracking --port /dev/ttyUSB0 --duration 30 --rate-hz 10
python -m examples.live_position /dev/ttyUSB0 --rate-hz 10
```

Use either `--interval` or `--rate-hz`. Both apply to periodic logs.
`ONCHANGED` logs keep their event triggers. Firmware, signal group, log and port
bandwidth determine the actual rate.

Replay preserves the recorded cadence. An interval option used during replay
sets the expected spacing for analysis. It does not resample the data.
Polling-only and event-only examples do not accept `--rate-hz`. See the
[output-rate guide](../README.md#receiver-output-rates) for supported rates and
measurement of the delivered rate.

## Antennas

Select an input with `--antenna`, or use `--swap-antennas` to exchange roles and
negate dual-antenna baselines. Neither option changes RF power or signal groups.

For E6-HAS or B2b-PPP, connect the broadband helix to ANT1. See the
[UM982 frequency table](https://en.unicorecomm.com/products/um982/).
C/N₀ and heading show antenna activity, but not whether the receiver tracks
corrections or uses PPP.

For orbit comparisons, supply a matching precise product. Sidereal analysis
needs a second day of data. Accuracy checks need independent reference data.
Live examples change receiver settings only through their documented options.
`--augment` may change the signal group, which the receiver saves automatically
before rebooting. Other augmentation settings are not explicitly saved.

## Projects

### Position, RTK and PPP

- [`b2b_correction_audit`](b2b_correction_audit/README.md): Checks PPP-B2b and optional Galileo HAS delivery beside PPP navigation epochs.
- [`base_station_survey`](base_station_survey/README.md): Averages repeated fixes until a base-station position converges.
- [`has_b2b_ppp_fix`](has_b2b_ppp_fix/README.md): Averages Galileo E6-HAS and BeiDou B2b-PPP fixes with divergence telemetry.
- [`live_position`](live_position/README.md): Streams GGA fixes and reconnects after receiver transport failures.
- [`ntrip_client`](ntrip_client/README.md): Applies public NTRIP RTCM corrections to a UM982 rover.
- [`ntrip_sources`](ntrip_sources/README.md): Lists caster mountpoints and their advertised locations.
- [`ntrip_server`](ntrip_server/README.md): Serves reference-station RTCM over NTRIP with TLS and optional guest access.
- [`offline_ppp`](offline_ppp/README.md): Records static observations and processes them later with CODE products and Python PPP.
- [`position_tracking`](position_tracking/README.md): Tracks positions, prefers full PPP fixes, and reports precision and satellite signals.
- [`position_precision`](position_precision/README.md): Matches GGA and GST by antenna and UTC time and exports precision to GeoJSON.
- [`postprocessed_rtk`](postprocessed_rtk/README.md): Runs RTKLIB with rover, base and navigation RINEX files.
- [`ppp_filter_inspector`](ppp_filter_inspector/README.md): Inspects PPP residuals, SSR coverage, and RTOS CPU load.
- [`precise_fix`](precise_fix/README.md): Averages a static occupation with outlier checks and a serial-correlation screening estimate.
- [`raim_fde`](raim_fde/README.md): Runs RAIM fault detection, exclusion and protection levels.
- [`rtk_outage_lab`](rtk_outage_lab/README.md): Measures RTK outage timelines, observed recoveries and censored outcomes.
- [`rtk_quality`](rtk_quality/README.md): Summarizes fix type, correction age and availability.
- [`uere_budget`](uere_budget/README.md): Estimates user range error from position uncertainty and DOP.
- [`wls_position`](wls_position/README.md): Solves a position from pseudoranges with weighted least squares.

### Geometry, orbits and attitude

- [`attitude_budget`](attitude_budget/README.md): Turns baseline noise into heading and pitch uncertainty.
- [`azel_crosscheck`](azel_crosscheck/README.md): Checks broadcast-orbit azimuth and elevation against SATVIS2.
- [`broadcast_orbit_audit`](broadcast_orbit_audit/README.md): Compares broadcast orbits with a precise SP3 product.
- [`coordinate_frames`](coordinate_frames/README.md): Converts between ECEF, geodetic, ENU and baselines.
- [`crs_transform`](crs_transform/README.md): Transforms 3D coordinates with optional PROJ integration.
- [`dop_geometry`](dop_geometry/README.md): Computes DOP values from satellite geometry.
- [`doppler_velocity`](doppler_velocity/README.md): Solves receiver velocity and clock drift from Doppler.
- [`elevation_optimizer`](elevation_optimizer/README.md): Finds the elevation mask with the best satellite geometry.
- [`ephemeris_orbit`](ephemeris_orbit/README.md): Propagates broadcast ephemerides for four constellations.
- [`heading_attitude`](heading_attitude/README.md): Turns a dual-antenna baseline into heading and pitch.
- [`vadase`](vadase/README.md): Solves displacement and velocity from time-differenced carrier phase.

### Signals, antennas and interference

- [`antenna_gain_pattern`](antenna_gain_pattern/README.md): Fits an empirical received C/N0 elevation pattern.
- [`cw_jamming`](cw_jamming/README.md): Classifies continuous-wave jamming from JAMSTATUS and FREQJAMSTATUS.
- [`dual_antenna_rf_audit`](dual_antenna_rf_audit/README.md): Pairs ANT1 and ANT2 C/N0 at shared epochs and summarizes differences by signal and elevation.
- [`interference_monitor`](interference_monitor/README.md): Alerts on jamming, spoofing and C/N0 dropouts.
- [`satellite_monitor`](satellite_monitor/README.md): Shows visibility, sky plot and constellation counts.
- [`signal_group_study`](signal_group_study/README.md): Compares satellites and signals across signal-group settings.
- [`signal_quality_report`](signal_quality_report/README.md): Reports C/N0 percentiles, lock time and channel use.
- [`spoof_dual_antenna`](spoof_dual_antenna/README.md): Cross-checks heading, visibility and spoof indicators.
- [`zero_baseline_lab`](zero_baseline_lab/README.md): Measures double-difference noise between two receivers on a zero baseline.

### Observations and measurement quality

- [`field_recording`](field_recording/README.md): Records and verifies segmented receiver byte streams.
- [`unattended_station`](unattended_station/README.md): Records resumable research segments and a station journal.
- [`polar_ionosphere`](polar_ionosphere/README.md): Compares code TEC proxies with signal tracking and receiver status.
- [`ice_motion`](ice_motion/README.md): Computes position-derived ECEF and ENU motion from field data.
- [`research_session`](research_session/README.md): Records observations and ephemerides and exports reproducible RINEX and provenance.
- [`compressed_observation_audit`](compressed_observation_audit/README.md): Compares RANGECMP reconstructions with RANGE and reports the wire-size ratio.
- [`satellite_health_timeline`](satellite_health_timeline/README.md): Reports time-stamped GPS, Galileo, GLONASS and BeiDou health from receiver logs.
- [`qzss_disaster_report`](qzss_disaster_report/README.md): Validates and inspects QZSS disaster-report sentences.
- [`code_carrier_divergence`](code_carrier_divergence/README.md): Tracks code-carrier divergence and resets after cycle slips.
- [`cycle_slip_detection`](cycle_slip_detection/README.md): Flags cycle slips from Doppler consistency.
- [`hatch_smoothing`](hatch_smoothing/README.md): Smooths code with carrier phase and resets on cycle slips.
- [`multipath_analysis`](multipath_analysis/README.md): Calculates RMS code-minus-carrier residuals as a multipath proxy.
- [`multipath_vs_mask`](multipath_vs_mask/README.md): Sweeps elevation masks and checks receiver state.
- [`sidereal_multipath`](sidereal_multipath/README.md): Checks whether multipath repeats after one sidereal day.
- [`triple_frequency_closure`](triple_frequency_closure/README.md): Tests triple-frequency combinations that cancel geometry and ionosphere.

### Atmosphere and reflectometry

- [`gnss_reflectometry`](gnss_reflectometry/README.md): Estimates reflector heights and guides snow-depth and water-level comparisons, including a no-hardware demonstration.
- [`ionosphere_tec`](ionosphere_tec/README.md): Computes slant TEC, ROT and ROTI from dual-frequency ranges.
- [`klobuchar_vs_tec`](klobuchar_vs_tec/README.md): Compares Klobuchar delay with dual-frequency TEC.
- [`pwv_meteorology`](pwv_meteorology/README.md): Derives precipitable water vapour from zenith wet delay.
- [`scintillation_monitor`](scintillation_monitor/README.md): Computes an uncalibrated S4-like proxy from C/N₀.

### Time and startup

- [`clock_jump_forensics`](clock_jump_forensics/README.md): Flags code and carrier jumps that appear together across satellites.
- [`clock_stability`](clock_stability/README.md): Computes Allan deviation from receiver clock offsets.
- [`time_transfer`](time_transfer/README.md): Converts receiver UTC to GPST using leap seconds.
- [`ttff_profile`](ttff_profile/README.md): Measures time to first fix after cold or warm starts.

### Recording, export and navigation data

- [`journey_track`](journey_track/README.md): Reviews ground motion for sea, air and outdoor sport with optional dual-antenna baseline direction.
- [`navigation_message_hex`](navigation_message_hex/README.md): Dumps navigation messages as annotated hex.
- [`navigation_messages`](navigation_messages/README.md): Builds navigation tables, sky views and orbit figures.
- [`rinex_export`](rinex_export/README.md): Writes multi-GNSS RINEX 3.05 from RANGE logs with an omission report.
- [`rinex_navigation`](rinex_navigation/README.md): Exports GPS, Galileo, BeiDou and GLONASS ephemerides as RINEX navigation data.
- [`telemetry_bridge`](telemetry_bridge/README.md): Streams decoded frames as newline-delimited JSON.

### Receiver and baseband diagnostics

- [`baseband_conformance`](baseband_conformance/README.md): Sends baseband commands and records ACKs, rejects and state changes.
- [`baseband_epoch_audit`](baseband_epoch_audit/README.md): Audits diagnostic counters and PTOBSINFO tracking slots.
- [`baseband_notice_console`](baseband_notice_console/README.md): Rebuilds baseband configuration from diagnostic notices.
- [`raw_data_tracking`](raw_data_tracking/README.md): Parses raw baseband containers, inner messages and notices.
- [`tracking_field_lab`](tracking_field_lab/README.md): Correlates unknown tracking fields with your own labels.

### Controlled scientific experiments

- [`spatial_tec`](spatial_tec/README.md): Compares TEC changes at two stations.
- [`noise_multipath`](noise_multipath/README.md): Compares shared-antenna noise and repeat-track measurements.
- [`multifrequency_slips`](multifrequency_slips/README.md): Tests ideal responses to injected cycle slips.
- [`uncertainty_coverage`](uncertainty_coverage/README.md): Compares reported uncertainty with position errors.
- [`phase_fluctuations`](phase_fluctuations/README.md): Measures carrier phase variability.
- [`orbit_position_effect`](orbit_position_effect/README.md): Estimates the position effect of satellite state errors.
