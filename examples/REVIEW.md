# Example reference review

Reviewed the 79 runnable projects, their documented inputs and outputs, shared
capture adapters, and automated contracts. Most are useful references within a
specific scope. A receiver workflow, a numerical demonstration and a validated
field measurement are different deliverables: the table below identifies what
each example can support and what additional evidence its use case needs.

This review uses source inspection, captured-wire replay, synthetic numerical
cases and the repository's independent reference tests. It does not establish
field accuracy, firmware behavior on every receiver, or service reliability
under a hardware soak. Short fixtures demonstrate decoding and integration;
they cannot replace an occupation, continuous carrier arc or controlled campaign.

## Improvements applied

- Centralized antenna routing for custom replay and live paths. Fixed ambiguous
  navigation-log swaps in the library; `antenna_log(..., swapped=True)` resolves
  the effective input while retaining the logical analysis key and real wire
  identity. Primary-only quantities are checked against the effective input.
- Added `um982py.capture.select_position(records, epoch, tolerance)`. It requires
  computed, timestamped, finite terrestrial receiver coordinates and selects the
  nearest absolute-GPST epoch, with earlier ties. WLS, RAIM, az/el, coordinate
  conversion, spoof-heading and Klobuchar examples now use it instead of unrelated
  snapshots. Spoof checks collect their logs together and report which checks
  have sufficient evidence.
- Split cycle-slip comparisons at long gaps and lock resets, rejected duplicate
  or reversed epochs, and exposed tested/unobserved increment counts. A single
  observation epoch cannot report a successful slip test.
- Rejected duplicate satellites and mixed constellations in the four-state WLS
  model. Clarified RAIM's illustrative single-fault slope bounds and the
  distinction between its initial alarm and post-exclusion test.
- Prevented input/report aliasing, including hardlinks and auxiliary CSV outputs,
  and applied the same parser to CSV scientific tools and file-based workflows.
- Made default gain-pattern and navigation-hex output parseable as one JSON
  document. Added missing satellite identities to orbit reports and distinguished
  incomplete evidence in orbit, mask, spoofing and baseband reports.
- Replaced single-frame replay instructions that implied a completed temporal or
  multi-source analysis. Clarified that a coordinate round trip tests conversion,
  not independent baseline accuracy.
- Corrected NTRIP availability sampling at floating-point time boundaries so a
  nominal one-second cadence does not drop samples and bias the ready percentage.

## Reference scope by project

“Workflow” demonstrates integration and ownership of resources. “Diagnostic”
reports observed receiver behavior. “Model” teaches a calculation with explicit
assumptions. “Experiment” needs a designed collection and independent evidence.
These are intended uses, not certification or deployment-readiness ratings.

| Project | Reference use | Preconditions and interpretation |
| --- | --- | --- |
| [antenna_gain_pattern](antenna_gain_pattern/README.md) | Experiment: received C/N0 versus elevation | Matched sky/range epochs and one signal; cable, transmitter and surroundings remain in the fit. |
| [attitude_budget](attitude_budget/README.md) | Model: baseline uncertainty propagation | Use baseline component uncertainty; absolute position sigma cannot substitute for it. |
| [azel_crosscheck](azel_crosscheck/README.md) | Diagnostic: broadcast versus SATVIS2 angles | Valid nearby observer position and suitable ephemerides; receiver agreement is not independent orbit truth. |
| [b2b_correction_audit](b2b_correction_audit/README.md) | Diagnostic: B2b correction consistency | Match satellite, issue and epoch; decoded corrections alone do not prove receiver application. |
| [base_station_survey](base_station_survey/README.md) | Workflow: stationary reference occupation | Require convergence and stable setup; averaging does not remove datum, antenna or common biases. |
| [baseband_conformance](baseband_conformance/README.md) | Diagnostic: command/reply evidence | Attribute actual baseband notices; missing families are incomplete, and disruptive probes are explicit. |
| [baseband_epoch_audit](baseband_epoch_audit/README.md) | Diagnostic: native counters and tracking slots | Native tags have no assumed counter frequency, wrap modulus or guaranteed GPST relationship. |
| [baseband_notice_console](baseband_notice_console/README.md) | Diagnostic: observed event transitions | Silence does not establish state; notice-gate cleanup is not readback of its unknown original state. |
| [broadcast_orbit_audit](broadcast_orbit_audit/README.md) | Experiment: broadcast/precise orbit comparison | Align satellite, epoch, frame and clock conventions; report missing products and interpolation limits. |
| [clock_jump_forensics](clock_jump_forensics/README.md) | Diagnostic: common phase/code discontinuities | Use coincident measurements; common jumps suggest a clock event without establishing its cause. |
| [clock_stability](clock_stability/README.md) | Model: receiver clock stability statistics | Requires sufficient regular epochs; receiver clock estimates are not independent oscillator measurements. |
| [code_carrier_divergence](code_carrier_divergence/README.md) | Experiment: continuous-arc divergence | Separate ambiguity resets and frequency changes; code noise and ionosphere remain confounded. |
| [compressed_observation_audit](compressed_observation_audit/README.md) | Diagnostic: observation representation consistency | Match source, signal and epoch; quantization and absent fields must remain distinguishable from zero. |
| [coordinate_frames](coordinate_frames/README.md) | Model: geodetic/ECEF/ENU transforms | Match position/baseline epochs and use the physical primary origin; round-trip residuals are numerical consistency. |
| [crs_transform](crs_transform/README.md) | Workflow: explicit coordinate transformation | Supply correct source/target CRS, epoch and available grids; transformation quality depends on those choices. |
| [cw_jamming](cw_jamming/README.md) | Diagnostic: interference indicators | Receiver C/N0 and jam telemetry are indirect; they do not identify a transmitter or calibrated RF power. |
| [cycle_slip_detection](cycle_slip_detection/README.md) | Diagnostic: Doppler/phase discontinuities | Requires observed increments within bounded gaps; lock resets are new arcs and flags are candidates. |
| [dop_geometry](dop_geometry/README.md) | Model: geometry-only dilution | Geometry and weighting determine DOP; it is not a measured position-error distribution. |
| [doppler_velocity](doppler_velocity/README.md) | Model: velocity from Doppler | Match satellite states and time, estimate receiver clock drift; wave interpretation needs external motion validation. |
| [dual_antenna_rf_audit](dual_antenna_rf_audit/README.md) | Experiment: antenna-path comparison | Match signals and epochs; cable/front-end differences and sky geometry require controlled comparisons. |
| [elevation_optimizer](elevation_optimizer/README.md) | Experiment: mask trade-off | Noise and geometry vary together; verify the chosen mask on another collection. |
| [ephemeris_orbit](ephemeris_orbit/README.md) | Model: broadcast propagation | Offsets are relative to each ephemeris, not a common epoch; health/age selection and uncertainty are outside this demonstration. |
| [field_recording](field_recording/README.md) | Workflow: preserve/replay field data | Keep raw bytes, metadata and manifests; loss counters and interrupted-session state matter. |
| [gnss_reflectometry](gnss_reflectometry/README.md) | Experiment: reflector-height retrieval | Continuous elevation arcs and suitable reflecting surfaces; snow/water interpretations need surveyed datum and field references. |
| [has_b2b_ppp_fix](has_b2b_ppp_fix/README.md) | Workflow: receiver PPP occupation | Service availability, convergence, freshness and datum must be checked; a PPP label alone is insufficient. |
| [hatch_smoothing](hatch_smoothing/README.md) | Model: carrier-smoothed code | Reset on discontinuities; smoothing reduces code noise but retains bias and can accumulate ionospheric divergence. |
| [heading_attitude](heading_attitude/README.md) | Workflow: receiver dual-antenna attitude | Respect antenna direction, installation offset and solution status; heading precision depends on baseline geometry. |
| [ice_motion](ice_motion/README.md) | Experiment: displacement time series | Ordered position epochs, a stable reference and independent site evidence; receiver motion is not automatically ice motion. |
| [interference_monitor](interference_monitor/README.md) | Diagnostic: combined receiver alarms | Missing telemetry remains unavailable; indicators support investigation rather than causal attribution. |
| [ionosphere_tec](ionosphere_tec/README.md) | Model: dual-frequency ionosphere observables | Ambiguities and hardware biases limit absolute TEC; preserve continuous signal identity. |
| [journey_track](journey_track/README.md) | Workflow: motion/position reporting | Check stale and invalid fixes, source transitions and measured cadence; reported precision is not surveyed accuracy. |
| [klobuchar_vs_tec](klobuchar_vs_tec/README.md) | Model: broadcast versus code-derived delay | Match observer/visibility epochs and valid coefficients; uncalibrated differential code biases remain. |
| [live_position](live_position/README.md) | Workflow: minimal live position consumer | Check validity, freshness and predicted-fix indicators; this is the preferred basic integration reference. |
| [multifrequency_slips](multifrequency_slips/README.md) | Model: integer-slip detectability | Enumerates assumed frequencies/thresholds; a simulated detection matrix is not a measured detection rate. |
| [multipath_analysis](multipath_analysis/README.md) | Experiment: code-minus-carrier residuals | Detrend continuous arcs with enough samples; residuals include noise and model error as well as multipath. |
| [multipath_vs_mask](multipath_vs_mask/README.md) | Experiment: mask/residual trade-off | Replay filters one pass; synthetic inverse-sine behavior is an assumption, and empty masks have no measured RMS. |
| [navigation_message_hex](navigation_message_hex/README.md) | Diagnostic: decoded payload bytes | Exact wire identity and byte offsets support decoder investigation; reserved bytes have no inferred meaning. |
| [navigation_messages](navigation_messages/README.md) | Model: orbit/sky visualizations | Use an appropriate observer and ephemerides; figures illustrate propagation, not a validated navigation solution. |
| [noise_multipath](noise_multipath/README.md) | Experiment: shared/separate-path comparison | Supply controlled paired data and compatible repeat geometry; variance attribution depends on those controls. |
| [ntrip_client](ntrip_client/README.md) | Workflow: rover correction session | Check correction age, reconnect behavior, GGA and station consistency; successful transport is not proof of an RTK fix. |
| [ntrip_server](ntrip_server/README.md) | Workflow: reference-station correction service | Review ARP coordinates, authentication, station identity and network configuration; deployment needs operational monitoring. |
| [ntrip_sources](ntrip_sources/README.md) | Workflow: source-table discovery | Advertised formats/coverage are server metadata; actual availability requires a connection and usable corrections. |
| [offline_ppp](offline_ppp/README.md) | Workflow: external PPP processing | Requires compatible products, antenna metadata and an installed engine; preserve commands and provenance. |
| [orbit_position_effect](orbit_position_effect/README.md) | Model: linearized orbit/clock error effect | Input rows share an epoch and conventions; conditioning and linearization bound the inference. |
| [phase_fluctuations](phase_fluctuations/README.md) | Model: detrended phase on prepared arcs | Supply range-increasing metres and explicit arc IDs; gap rejection does not independently validate the physical source. |
| [polar_ionosphere](polar_ionosphere/README.md) | Experiment: ionospheric event statistics | Continuous observations, geometry and independent event labels; association alone does not prove cause. |
| [position_precision](position_precision/README.md) | Diagnostic: receiver uncertainty reporting | Keep coordinate axes, covariance and reported confidence definitions explicit; no surveyed accuracy claim. |
| [position_tracking](position_tracking/README.md) | Workflow: position selection and track export | Handle validity, source changes, freshness and antenna routing; PPP availability may differ by input. |
| [postprocessed_rtk](postprocessed_rtk/README.md) | Workflow: external RTK processing | Compatible rover/base/navigation files and reviewed base coordinates; inspect engine status and ambiguity quality. |
| [ppp_filter_inspector](ppp_filter_inspector/README.md) | Diagnostic: receiver filter telemetry | Firmware fields and receiver estimates are the evidence; they do not reproduce an independent PPP filter. |
| [precise_fix](precise_fix/README.md) | Workflow: stationary occupation | Require accepted epochs and explicit convergence; time correlation and systematic bias survive averaging. |
| [pwv_meteorology](pwv_meteorology/README.md) | Model: wet-delay conversion to PWV | Requires valid delay, pressure and temperature assumptions; a manual calculation is not a receiver-derived weather observation. |
| [qzss_disaster_report](qzss_disaster_report/README.md) | Diagnostic: QZSS message decoding | Validate framing, supported fields and archive provenance; decoded reports are not a replacement for official alerts. |
| [raim_fde](raim_fde/README.md) | Model: residual test and exclusion | Single-constellation independent ranges; slope bounds lack missed-detection risk and are not operational protection levels. |
| [raw_data_tracking](raw_data_tracking/README.md) | Diagnostic: tracking/observation inspection | Retain epoch, signal, validity and lock identity; raw observations alone do not solve position. |
| [research_session](research_session/README.md) | Workflow: research capture/export provenance | Preserve station metadata and paired-antenna identity; independent reference comparison needs compatible frames/epochs. |
| [rinex_export](rinex_export/README.md) | Workflow: observation conversion | Correct signal mapping, phase convention, epochs and station/antenna metadata; file validity does not establish field accuracy. |
| [rinex_navigation](rinex_navigation/README.md) | Workflow: navigation conversion | Preserve broadcast time systems, issue and health fields; verify downstream engine support. |
| [rtk_outage_lab](rtk_outage_lab/README.md) | Experiment: fix loss/recovery | Independent outage events, continuous position coverage and sustained recovery; retain censored outcomes. |
| [rtk_quality](rtk_quality/README.md) | Diagnostic: quality and campaign comparison | Fix class, correction age and reported sigma are distinct; accuracy comparison needs independent truth and labels. |
| [satellite_health_timeline](satellite_health_timeline/README.md) | Diagnostic: reported satellite health changes | Time-order status evidence and keep missing records unknown; silence is not restored health. |
| [satellite_monitor](satellite_monitor/README.md) | Workflow: sky visibility | Constellation and PRN identity, receiver epochs and signal availability matter; visibility is not used-in-solution status. |
| [scintillation_monitor](scintillation_monitor/README.md) | Model: C/N0 variability proxy | Requires regular per-signal samples; filtered C/N0 lacks calibrated intensity and thermal-noise correction. |
| [sidereal_multipath](sidereal_multipath/README.md) | Experiment: repeating residual patterns | Separate training and test captures with aligned signal/geometry; evaluate improvement on held-out data. |
| [signal_group_study](signal_group_study/README.md) | Experiment: receiver configuration comparison | Capture before/after state and restoration; sequential sky changes can confound configuration effects. |
| [signal_quality_report](signal_quality_report/README.md) | Diagnostic: reception summary | Aggregate only compatible signals/epochs; receiver C/N0 and alarms do not measure antenna calibration. |
| [spatial_tec](spatial_tec/README.md) | Model: paired-station TEC changes | Match time, frequency and phase conventions; spatial interpretation requires actual station geometry and continuous arcs. |
| [spoof_dual_antenna](spoof_dual_antenna/README.md) | Diagnostic: heading/sky/spoof consistency | Require the advertised evidence; successive sky snapshots are not separate antenna feeds, and no alarms cannot authenticate signals. |
| [telemetry_bridge](telemetry_bridge/README.md) | Workflow: serialize decoded wire data | Valid framing and provenance are the result; exporting unrelated frames is legitimate even without a navigation solution. |
| [time_transfer](time_transfer/README.md) | Diagnostic: time and PPS observations | Distinguish UTC from GPST and receiver timestamps from external PPS measurements; absolute transfer needs calibrated delays. |
| [tracking_field_lab](tracking_field_lab/README.md) | Experiment: labelled tracking events | Independent event labels and continuous capture; receiver indicators alone cannot create ground-truth labels. |
| [triple_frequency_closure](triple_frequency_closure/README.md) | Model: multi-frequency consistency | Match simultaneous continuous carriers; closure detects some combinations and has insensitive modes. |
| [ttff_profile](ttff_profile/README.md) | Experiment: time to first fix | Controlled restart conditions and explicit reset time; failed/censored runs must remain in the report. |
| [uere_budget](uere_budget/README.md) | Model: range-error budget | Component assumptions and correlations determine the budget; a quadrature sum is not independent measured UERE. |
| [unattended_station](unattended_station/README.md) | Workflow: bounded station recording/health | Monitor gaps, storage, reconnects and manifests; hardware/power-loss testing is needed for the intended installation. |
| [uncertainty_coverage](uncertainty_coverage/README.md) | Experiment: empirical sigma coverage | Independent truth in compatible axes/epochs; temporal correlation limits confidence in finite-sample coverage. |
| [vadase](vadase/README.md) | Model: phase-difference displacement | Continuous carrier arcs, satellite motion and clock estimation; event attribution needs independent motion evidence. |
| [wls_position](wls_position/README.md) | Model: four-state code position solution | Unique satellites from one constellation, suitable ephemerides and convergence; receiver agreement is not surveyed truth. |
| [zero_baseline_lab](zero_baseline_lab/README.md) | Experiment: receiver/path noise | A real common-input setup and synchronized signals; ordinary separated antennas do not constitute a zero baseline. |

## Choosing and extending a reference

Start integrations with `live_position`, `field_recording`, `research_session`,
`position_tracking` or the relevant NTRIP/RINEX workflow. Reuse public library
capture, antenna, observation and coordinate APIs rather than copying a CLI's
argument handling into application code. For a scientific example, retain its
units, signal identity, gap rules, provenance and unavailable-result states when
adapting it. State which output is receiver-reported, computed, simulated or
compared with independent truth.

The next useful validation is use-case-specific: a stationary surveyed occupation,
a known motion/phase discontinuity, a controlled antenna comparison, an external
clock measurement, or a receiver/network/storage soak. Passing replay and
numerical tests alone does not supply that evidence.

## Validation

The completed review passes **4,162 tests**, Ruff lint/format checks and strict
mypy. There are 82 skips for receiver hardware, external clients/tools and
prepared datasets, plus the existing GeoRinex navigation-field expected failure.
The GeoRinex observation comparison emits two existing NumPy warnings. Tests
include every project's import/CLI contract, documented fixture replays, local
TCP/NTRIP integration and regressions for the corrected evidence boundaries.
