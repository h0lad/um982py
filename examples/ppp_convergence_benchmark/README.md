# PPP convergence benchmark

Measure how long a UM982 needs to produce a sustained PPP-quality position and
compare the achieved errors against an optional surveyed reference.

## Background

Low-cost multi-frequency receivers combined with open PPP services (Galileo
HAS, BeiDou B2b-PPP) are increasingly used where RTK infrastructure is
unavailable.  A key metric is the convergence time: how long after enabling the
service does the reported precision stay within an application limit?

This example follows the benchmarking approach in

> Marut, G., Hadas, T., Kazmierski, K., et al. (2024). Affordable Real-Time PPP—
> Combining Low-Cost GNSS Receivers with Galileo HAS Corrections in Static,
> Pseudo-Kinematic, and UAV Experiments. *Remote Sensing*, 16(21), 4008.
> doi:10.3390/rs16214008

## Method

The example subscribes to `BESTNAV` at the requested rate and feeds each epoch
into a `ConvergenceMonitor` only when `--trust-host-clock` is supplied. Only
valid PPP or PPP-converging solution types enter the statistics, while
 duplicate, reversed and missing epochs are counted and excluded. Gaps are counted. The
monitor requires the reported horizontal RMS
and vertical standard deviation to stay inside the given limits for a sustained
`hold_seconds` window.  When this succeeds, the time since start is reported as
`convergence_s`.

If `--reference-ecef X,Y,Z` is supplied, each epoch is also compared with that
ECEF position and an empirical error CDF is produced.

## Run

Static benchmark with default 20 cm horizontal / 40 cm vertical limit:

```bash
python -m examples.ppp_convergence_benchmark \
    --port /dev/ttyUSB0 --baud 921600 \
    --service E6-HAS --trust-host-clock \
    --duration 600 --interval 1 \
    --reference-ecef 4027891.3,307045.5,4919474.1
```

Omit `--service` to benchmark the current receiver solution instead of
enabling a PPP service.

## Output

The JSON report contains:

- `summary` – total epochs, number of converged epochs, first fix time and
  convergence time
- `errors.horizontal_error_cdf_m` / `vertical_error_cdf_m` – 50th, 68th and
  95th percentiles against the reference
- `reported_precision` – same percentiles of the receiver-reported horizontal
  RMS and vertical std
- `epochs` – full per-epoch table

## Limitations

- Without `--trust-host-clock` freshness is unknown and convergence is censored.
  With it, the host UTC clock is assumed accurate, so verify it independently
  and
  verify the bundled leap-second table. The receiver epoch is never its own now.
- Convergence is defined by receiver-reported precision, not by comparison with
  an independent truth.
- If the receiver loses PPP before `hold_seconds` elapse, convergence is not
  reported.
- Reference errors include datum, antenna phase-centre and multipath biases that
  are not modelled here.
