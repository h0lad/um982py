# Examples

Run these examples to read receiver data and analyze GNSS measurements.

The [API guide](../README.md#find-the-right-api) lists supported imports and
explains which streaming or reconnecting session to use. Specialist helpers
are imported from their modules, and the package root exposes the main
workflows.

Workflow examples demonstrate library integration, while scientific
models and field experiments require the stated data and independent reference
measurements before their results support an accuracy or physical claim. Short
fixtures exercise decoding and integration, but an occupation, continuous
carrier arc or controlled campaign requires its own field data.

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

The shared parser rejects report paths that alias an input or another report,
including symlinks and hardlinks. Use distinct destinations for JSON, CSV and
other products. A successful command means its documented operation completed,
so inspect the report's status, convergence and alarms. In particular, zero detected
events in an incomplete capture is not a clean bill of health.

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

- [`b2b_correction_audit`](b2b_correction_audit/README.md): Checks PPP-B2b and optional Galileo HAS delivery beside PPP navigation epochs. Match satellite, issue and epoch; decoded corrections alone do not prove receiver application.
- [`base_station_survey`](base_station_survey/README.md): Averages repeated fixes until a base-station position converges. Require convergence and stable setup; averaging does not remove datum, antenna or common biases.
- [`has_b2b_ppp_fix`](has_b2b_ppp_fix/README.md): Averages Galileo E6-HAS and BeiDou B2b-PPP fixes with divergence telemetry. Service availability, convergence, freshness and datum must be checked; a PPP label alone is insufficient.
- [`maritime_cog_heading`](maritime_cog_heading/README.md): Compares single-antenna course over ground with dual-antenna heading for marine platforms. COG/heading differences include current, leeway and latency; they are not purely attitude errors.
- [`ppp_convergence_benchmark`](ppp_convergence_benchmark/README.md): Measures time-to-first-fix and sustained precision for PPP services, with optional reference-position error CDFs. Convergence is defined by receiver-reported precision, not independent truth.
- [`uncertainty_coverage`](uncertainty_coverage/README.md): Summarises reported BESTNAV standard deviations and checks their empirical coverage against the sample mean. Coverage fractions are optimistic because the same data set supplies both estimates.
- [`live_position`](live_position/README.md): Streams deduplicated GGA fixes in a refreshable dashboard with Doppler motion, detailed fix type, uncertainty, DOP and GNSS statistics, and reconnects after receiver transport failures. Check validity, freshness and predicted-fix indicators; this is the preferred basic integration reference.
- [`ntrip_client`](ntrip_client/README.md): Applies public NTRIP RTCM corrections to a UM982 rover with optional RTK reliability settings. Check correction age, reconnect behavior, GGA and station consistency; successful transport is not proof of an RTK fix.
- [`ntrip_sources`](ntrip_sources/README.md): Lists caster mountpoints and their advertised locations. Advertised formats/coverage are server metadata; actual availability requires a connection and usable corrections.
- [`ntrip_server`](ntrip_server/README.md): Serves reference-station RTCM over NTRIP with TLS and optional guest access. Review ARP coordinates, authentication, station identity and network configuration; deployment needs operational monitoring.
- [`offline_ppp`](offline_ppp/README.md): Records static observations and processes them later with CODE products and Python PPP. Requires compatible products, antenna metadata and an installed engine; preserve commands and provenance.
- [`position_tracking`](position_tracking/README.md): Tracks positions, prefers full PPP fixes, and reports precision and satellite signals. Handle validity, source changes, freshness and antenna routing; PPP availability may differ by input.
- [`position_precision`](position_precision/README.md): Matches GGA and GST by antenna and UTC time and exports precision to GeoJSON. Keep coordinate axes, covariance and reported confidence definitions explicit; no surveyed accuracy claim.
- [`postprocessed_rtk`](postprocessed_rtk/README.md): Runs RTKLIB with rover, base and navigation RINEX files. Compatible rover/base/navigation files and reviewed base coordinates; inspect engine status and ambiguity quality.
- [`ppp_filter_inspector`](ppp_filter_inspector/README.md): Inspects PPP residuals, SSR coverage, and RTOS CPU load. Firmware fields and receiver estimates are the evidence; they do not reproduce an independent PPP filter.
- [`precise_fix`](precise_fix/README.md): Averages a static occupation with outlier checks and a serial-correlation screening estimate. Require accepted epochs and explicit convergence; time correlation and systematic bias survive averaging.
- [`raim_fde`](raim_fde/README.md): Demonstrates residual fault detection, exclusion and single-fault position-error slope bounds. Single-constellation independent ranges; slope bounds lack missed-detection risk and are not operational protection levels.
- [`rtk_outage_lab`](rtk_outage_lab/README.md): Measures RTK outage timelines, observed recoveries and censored outcomes. Independent outage events, continuous position coverage and sustained recovery; retain censored outcomes.
- [`rtk_quality`](rtk_quality/README.md): Summarizes fix type, correction age and availability. Fix class, correction age and reported sigma are distinct; accuracy comparison needs independent truth and labels.
- [`uere_budget`](uere_budget/README.md): Estimates user range error from position uncertainty and DOP. Component assumptions and correlations determine the budget; a quadrature sum is not independent measured UERE.
- [`wls_position`](wls_position/README.md): Solves a position from pseudoranges with weighted least squares. Unique satellites from one constellation, suitable ephemerides and convergence; receiver agreement is not surveyed truth.

### Geometry, orbits and attitude

- [`attitude_budget`](attitude_budget/README.md): Turns baseline noise into heading and pitch uncertainty. Use baseline component uncertainty; absolute position sigma cannot substitute for it.
- [`azel_crosscheck`](azel_crosscheck/README.md): Checks broadcast-orbit azimuth and elevation against SATVIS2. Valid nearby observer position and suitable ephemerides; receiver agreement is not independent orbit truth.
- [`broadcast_orbit_audit`](broadcast_orbit_audit/README.md): Compares broadcast orbits with a precise SP3 product. Align satellite, epoch, frame and clock conventions; report missing products and interpolation limits.
- [`coordinate_frames`](coordinate_frames/README.md): Converts between ECEF, geodetic, ENU and baselines. Match position/baseline epochs and use the physical primary origin; round-trip residuals are numerical consistency.
- [`crs_transform`](crs_transform/README.md): Transforms 3D coordinates with optional PROJ integration. Supply correct source/target CRS, epoch and available grids; transformation quality depends on those choices.
- [`dop_geometry`](dop_geometry/README.md): Computes DOP values from satellite geometry. Geometry and weighting determine DOP; it is not a measured position-error distribution.
- [`doppler_velocity`](doppler_velocity/README.md): Solves velocity and clock drift from GPS Doppler. The native receiver example compares ECEF velocity and per-axis uncertainty at matched epochs.
- [`elevation_optimizer`](elevation_optimizer/README.md): Finds the elevation mask with the best satellite geometry. Noise and geometry vary together; verify the chosen mask on another collection.
- [`ephemeris_orbit`](ephemeris_orbit/README.md): Propagates broadcast ephemerides for four constellations with each system's ICD constants and the BeiDou GEO frame rotation. Offsets are relative to each ephemeris, not a common epoch; time-system conversion, health/age selection and uncertainty are outside this demonstration.
- [`heading_attitude`](heading_attitude/README.md): Turns a dual-antenna baseline into heading and pitch. Respect antenna direction, installation offset and solution status; heading precision depends on baseline geometry.
- [`heading_baseline_constraint`](heading_baseline_constraint/README.md): Estimates heading and pitch while constraining the BSLNENUHD baseline to the measured antenna separation. Residuals are relative to the receiver's UNIHEADING, not independent truth.
- [`dual_rtk_consistency`](dual_rtk_consistency/README.md): Cross-checks position-derived baselines against UNIHEADING. Receiver outputs can share errors and are not independent truth.
- [`orbit_position_effect`](orbit_position_effect/README.md): Maps assumed orbit errors into expected horizontal, vertical and 3-D position errors through the current DOP. A first-order scalar approximation, not a rigorous covariance analysis.
- [`vadase`](vadase/README.md): Solves displacement and velocity from time-differenced carrier phase. Continuous carrier arcs, satellite motion and clock estimation; event attribution needs independent motion evidence.

### Signals, antennas and interference

- [`antenna_gain_pattern`](antenna_gain_pattern/README.md): Fits an empirical received C/N0 elevation pattern. Matched sky/range epochs and one signal; cable, transmitter and surroundings remain in the fit.
- [`cw_jamming`](cw_jamming/README.md): Summarizes receiver-reported interference indicators from JAMSTATUS and FREQJAMSTATUS. Receiver C/N0 and jam telemetry are indirect; they do not identify a transmitter or calibrated RF power.
- [`dual_antenna_rf_audit`](dual_antenna_rf_audit/README.md): Pairs ANT1 and ANT2 C/N0 at shared epochs and summarizes differences by signal and elevation. Match signals and epochs; cable/front-end differences and sky geometry require controlled comparisons.
- [`interference_monitor`](interference_monitor/README.md): Alerts on jamming, spoofing and C/N0 dropouts. Missing telemetry remains unavailable; indicators support investigation rather than causal attribution.
- [`urban_nlos_filter`](urban_nlos_filter/README.md): Classifies tracked satellites as LOS/unsure/NLOS from elevation and C/N0. A receiver-only heuristic; low-elevation/low-C/N0 signals can also be foliage or interference, not only urban multipath.
- [`satellite_monitor`](satellite_monitor/README.md): Shows visibility, sky plot and constellation counts. Constellation and PRN identity, receiver epochs and signal availability matter; visibility is not used-in-solution status.
- [`signal_group_study`](signal_group_study/README.md): Compares satellites and signals across signal-group settings. Capture before/after state and restoration; sequential sky changes can confound configuration effects.
- [`signal_quality_report`](signal_quality_report/README.md): Reports C/N0 percentiles, lock time and channel use. Aggregate only compatible signals/epochs; receiver C/N0 and alarms do not measure antenna calibration.
- [`spoof_dual_antenna`](spoof_dual_antenna/README.md): Cross-checks heading, visibility and spoof indicators. Require the advertised evidence; successive sky snapshots are not separate antenna feeds, and no alarms cannot authenticate signals.
- [`zero_baseline_lab`](zero_baseline_lab/README.md): Measures double-difference noise between two receivers on a zero baseline. A real common-input setup and synchronized signals; ordinary separated antennas do not constitute a zero baseline.

### Observations and measurement quality

- [`field_recording`](field_recording/README.md): Records and verifies segmented receiver byte streams. Keep raw bytes, metadata and manifests; loss counters and interrupted-session state matter.
- [`unattended_station`](unattended_station/README.md): Records resumable research segments and a station journal. Monitor gaps, storage, reconnects and manifests; hardware/power-loss testing is needed for the intended installation.
- [`polar_ionosphere`](polar_ionosphere/README.md): Compares code TEC proxies with signal tracking and receiver status. Continuous observations, geometry and independent event labels; association alone does not prove cause.
- [`ice_motion`](ice_motion/README.md): Computes position-derived ECEF and ENU motion from field data. Ordered position epochs, a stable reference and independent site evidence; receiver motion is not automatically ice motion.
- [`research_session`](research_session/README.md): Records observations and ephemerides and exports reproducible RINEX and provenance. Preserve station metadata and paired-antenna identity; independent reference comparison needs compatible frames/epochs.
- [`compressed_observation_audit`](compressed_observation_audit/README.md): Compares compressed observations with simultaneous RANGE data. Measures the wire-size ratio, GPS L1 pseudorange wraps and how often L2 phase resolves them.
- [`satellite_health_timeline`](satellite_health_timeline/README.md): Reports time-stamped GPS, Galileo, GLONASS and BeiDou health from receiver logs. Time-order status evidence and keep missing records unknown; silence is not restored health.
- [`qzss_disaster_report`](qzss_disaster_report/README.md): Validates and inspects QZSS disaster-report sentences. Validate framing, supported fields and archive provenance; decoded reports are not a replacement for official alerts.
- [`code_carrier_divergence`](code_carrier_divergence/README.md): Tracks code-carrier divergence and resets after cycle slips. Separate ambiguity resets and frequency changes; code noise and ionosphere remain confounded.
- [`cycle_slip_detection`](cycle_slip_detection/README.md): Flags cycle slips from Doppler consistency. Requires observed increments within bounded gaps; lock resets are new arcs and flags are candidates.
- [`hatch_smoothing`](hatch_smoothing/README.md): Smooths code with carrier phase and resets on cycle slips. Reset on discontinuities; smoothing reduces code noise but retains bias and can accumulate ionospheric divergence.
- [`multipath_analysis`](multipath_analysis/README.md): Calculates RMS code-minus-carrier residuals as a multipath proxy. Detrend continuous arcs with enough samples; residuals include noise and model error as well as multipath.
- [`multifrequency_slips`](multifrequency_slips/README.md): Detects cycle-slip candidates from dual-frequency geometry-free phase combinations. Jumps can also be caused by rapid ionospheric change; the flags are candidates, not confirmed slips.
- [`noise_multipath`](noise_multipath/README.md): Separates code-noise and multipath-bias proxies from code-minus-carrier residuals per short arc. The mean includes ambiguity offset and ionospheric drift; use as a relative quality proxy.
- [`phase_fluctuations`](phase_fluctuations/README.md): Estimates short-term carrier-phase fluctuation per satellite after removing a linear trend. Residuals contain multipath and scintillation; calibrate phase noise with a zero-baseline test.
- [`multipath_vs_mask`](multipath_vs_mask/README.md): Sweeps elevation masks and checks receiver state. Replay filters one pass; synthetic inverse-sine behavior is an assumption, and empty masks have no measured RMS.
- [`sidereal_multipath`](sidereal_multipath/README.md): Checks whether multipath repeats after one sidereal day. Separate training and test captures from different repeat days (at least 23 h apart), with aligned signal/geometry; evaluate improvement on held-out data.
- [`triple_frequency_closure`](triple_frequency_closure/README.md): Tests triple-frequency combinations that cancel geometry and ionosphere. Match simultaneous continuous carriers; closure detects some combinations and has insensitive modes.

### Atmosphere and reflectometry

- [`gnss_reflectometry`](gnss_reflectometry/README.md): Estimates reflector heights and guides snow-depth and water-level comparisons, including a no-hardware demonstration. Continuous elevation arcs and suitable reflecting surfaces; snow/water interpretations need surveyed datum and field references.
- [`spatial_tec`](spatial_tec/README.md): Compares matched slant-TEC changes between two stations. Requires synchronized continuous carrier arcs; it does not map pierce points or estimate absolute TEC.
- [`ionosphere_tec`](ionosphere_tec/README.md): Computes slant TEC, ROT and ROTI from dual-frequency ranges. Ambiguities and hardware biases limit absolute TEC; preserve continuous signal identity.
- [`klobuchar_vs_tec`](klobuchar_vs_tec/README.md): Compares Klobuchar delay with dual-frequency TEC. Match observer/visibility epochs and valid coefficients; uncalibrated differential code biases remain.
- [`pwv_meteorology`](pwv_meteorology/README.md): Derives precipitable water vapour from zenith wet delay. Requires valid delay, pressure and temperature assumptions; a manual calculation is not a receiver-derived weather observation.
- [`scintillation_monitor`](scintillation_monitor/README.md): Computes an uncalibrated S4-like proxy from C/N₀. Requires regular per-signal samples; filtered C/N0 lacks calibrated intensity and thermal-noise correction.

### Time and startup

- [`clock_jump_forensics`](clock_jump_forensics/README.md): Flags code and carrier jumps that appear together across satellites. Use coincident measurements; common jumps suggest a clock event without establishing its cause.
- [`clock_stability`](clock_stability/README.md): Computes Allan deviation from receiver clock offsets. Requires sufficient regular epochs; receiver clock estimates are not independent oscillator measurements.
- [`time_transfer`](time_transfer/README.md): Converts receiver UTC to GPST using leap seconds. Distinguish UTC from GPST and receiver timestamps from external PPS measurements; absolute transfer needs calibrated delays.
- [`ttff_profile`](ttff_profile/README.md): Measures time to first fix after cold or warm starts. Controlled restart conditions and explicit reset time; failed/censored runs must remain in the report.

### Recording, export and navigation data

- [`journey_track`](journey_track/README.md): Reviews ground motion for sea, air and outdoor sport from paired positions and Doppler velocity, with optional dual-antenna baseline direction. Check epoch pairing, stale and invalid fixes, source transitions and measured cadence; reported precision is not surveyed accuracy.
- [`navigation_message_hex`](navigation_message_hex/README.md): Dumps navigation messages as annotated hex. Exact wire identity and byte offsets support decoder investigation; reserved bytes have no inferred meaning.
- [`navigation_messages`](navigation_messages/README.md): Builds navigation tables, sky views and orbit figures. Use an appropriate observer and ephemerides; figures illustrate propagation, not a validated navigation solution.
- [`rinex_export`](rinex_export/README.md): Writes multi-GNSS RINEX 3.05 from RANGE logs with an omission report. Correct signal mapping, phase convention, epochs and station/antenna metadata; file validity does not establish field accuracy.
- [`rinex_navigation`](rinex_navigation/README.md): Exports GPS, Galileo, BeiDou and GLONASS ephemerides as RINEX navigation data. Preserve broadcast time systems, issue and health fields; verify downstream engine support.
- [`telemetry_bridge`](telemetry_bridge/README.md): Streams decoded frames as newline-delimited JSON. Valid framing and provenance are the result; exporting unrelated frames is legitimate even without a navigation solution.

### Receiver and DSP diagnostics

- [`baseband_conformance`](baseband_conformance/README.md): Sends baseband commands and records ACKs, rejects and state changes. Attribute actual baseband notices; missing families are incomplete, and disruptive probes are explicit.
- [`baseband_epoch_audit`](baseband_epoch_audit/README.md): Audits diagnostic counters and PTOBSINFO tracking slots. Native tags have no assumed counter frequency, wrap modulus or guaranteed GPST relationship.
- [`baseband_notice_console`](baseband_notice_console/README.md): Reports baseband state transitions from diagnostic notices. Silence does not establish state; notice-gate cleanup is not readback of its unknown original state.
- [`dsp_tracking`](dsp_tracking/README.md): Reads tracking, receiver, satellite-state, ephemeris and propagation data from DSP RAM through the boot menu. Prints dense engineering tables and supports offline replay of the RAM windows.
- [`inav_page_capture`](inav_page_capture/README.md): Captures the decoded Galileo E1-B I/NAV pages stored per signal, including odd-part OSNMA data. One snapshot returns one page per signal; sub-frame assembly needs repeated captures.
- [`raw_data_tracking`](raw_data_tracking/README.md): Parses raw DSP tracking containers, inner messages and notices. Retain epoch, signal, validity and lock identity; raw observations alone do not solve position.
- [`tracking_field_lab`](tracking_field_lab/README.md): Correlates unknown tracking fields with your own labels. Independent event labels and continuous capture; receiver indicators alone cannot create ground-truth labels.

### Controlled scientific experiments

- [`spatial_tec`](spatial_tec/README.md): Compares TEC changes at two stations. Match time, frequency and phase conventions; spatial interpretation requires actual station geometry and continuous arcs.
- [`noise_multipath`](noise_multipath/README.md): Compares shared-antenna noise and repeat-track measurements. Supply controlled paired data and compatible repeat geometry; variance attribution depends on those controls.
- [`multifrequency_slips`](multifrequency_slips/README.md): Tests ideal responses to injected cycle slips. Enumerates assumed frequencies/thresholds; a simulated detection matrix is not a measured detection rate.
- [`uncertainty_coverage`](uncertainty_coverage/README.md): Compares reported uncertainty with position errors. Independent truth in compatible axes/epochs; temporal correlation limits confidence in finite-sample coverage.
- [`phase_fluctuations`](phase_fluctuations/README.md): Measures carrier phase variability. Supply range-increasing metres and explicit arc IDs; gap rejection does not independently validate the physical source.
- [`orbit_position_effect`](orbit_position_effect/README.md): Estimates the position effect of satellite state errors. Input rows share an epoch and conventions; conditioning and linearization bound the inference.

## Adapting an example

Reuse public library capture, antenna, observation and coordinate APIs when
building an application. For scientific examples, retain the units, signal
identity, gap rules, provenance and unavailable-result states. Identify which
outputs are receiver-reported, computed, simulated or compared with independent
truth. Replay and numerical tests do not establish field accuracy or reliability
for a particular receiver, firmware and installation.
