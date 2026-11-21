# PPP filter and RTOS performance inspector

Inspect the receiver's internal PPP filter telemetry.

## Run

Run from the repository root after [installation](../README.md#running-the-examples).

Connect to a receiver:

```bash
python -m examples.ppp_filter_inspector --port /dev/ttyUSB0 --duration 4 \
    --record /tmp/ppp-debug.bin --json /tmp/ppp-debug.json
```

Replay a capture:

```bash
python -m examples.ppp_filter_inspector --replay /tmp/ppp-debug.bin \
    --json /tmp/ppp-replay.json
```

Join a PPP transcript with raw observations from the same receiver and session:

```bash
python -m examples.ppp_filter_inspector --replay /tmp/ppp-debug.bin \
    --range-replay /tmp/range.bin --json /tmp/ppp-replay.json
```

Use `--solver-trace /tmp/solver.txt` to include separately captured solver text.

## Inputs and results

Missing fields are `null`.
The selected antenna controls which PPP filter stream is analysed in both
live and replay modes. POSDEBUG and receiver-wide telemetry retain their
own scope. Each native frequency index reports residual RMS, the 95th
percentile of absolute residuals and the number of epochs with samples.
The report also groups residuals by satellite and native frequency index,
counts update failures by system and frequency, and preserves the native
ambiguity tokens. `iode_satellites` identifies the satellites listed by the
ephemeris check where the slot is known.

The RANGE join uses exact time of week and the selected antenna. It retains
each candidate signal's C/N₀, lock time and raw observations under the
corresponding satellite. PPP frequencies retain their native indices.
GPS and Galileo slots have resolved PRNs. Other slots retain their native
numbers. A time of week found in multiple GPS weeks is left unmatched.

The solver trace reader accepts gap and position covariance, reset diagnostics,
IODE mismatches and solution lines with clock, DOP and troposphere values.
These data require a separate trace source.

## Understanding the result

The report keeps values with unverified units or meanings in their original form.

## References

- Zumberge et al. (1997), *Journal of Geophysical Research*, 102(B3).
- Galileo HAS SIS ICD, Issue 1.0 (2022).
