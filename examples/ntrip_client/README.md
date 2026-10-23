# NTRIP rover client

This example connects a UM982 **rover** receiver to an NTRIP caster and sends
the received RTCM data to the receiver. The receiver combines that data with
its own satellite observations and computes the position and RTK solution.
The Python client transports data and reports the receiver's results without
calculating the RTK solution itself.

Run commands from `lib/um982py`. From the outer workspace in this checkout,
first run `cd lib/um982py` and follow [the example installation instructions](../README.md#running-the-examples).

## Run

### 1. Before you connect

Connect a suitable GNSS antenna to the UM982, give it a clear view of the sky,
and connect the receiver to Linux. Only one process can use its serial port at
a time. The example sets the receiver to **rover mode** and does not restore
the previous mode when it stops. The serial device defaults to `/dev/ttyUSB0` at
`921600` baud. Check the device, permissions and existing users with:

```bash
ls -l /dev/ttyUSB*
id
fuser /dev/ttyUSB0
```

Get the following from your correction provider or base-station operator:

| Input | Meaning |
| --- | --- |
| Caster hostname and port | The server address, for example `rtk2go.com` and port `2101`. |
| Mountpoint | The case-sensitive name of the correction stream, for example `Weinstadt`. It is part of the URL after `/`. Choose a suitable station for your location. |
| NTRIP version | Protocol version 1 or 2, according to the provider. |
| Access | Guest access or the provider's username and password. RTK2go requests a real email as username and `none` as password. |
| Transport | `https` uses TLS and checks the hostname and certificate, while `http` is unencrypted. |
| Position requirement | Some networks need a GGA sentence containing the rover's approximate position before they send corrections. Ask the provider if unsure. |

You do **not** enter base-station coordinates or antenna H/E/N offsets into this
rover example. If GGA is enabled, the client gets an approximate fix from the
receiver and sends it to the caster, waiting for a valid fix if none is
available initially. GGA is updated approximately every 10 seconds. The
caster can see that position, and with HTTP, the position and any credentials are
sent without encryption. Use HTTPS when available and appropriate for the
provider. `--no-gga` disables this, but streams requiring GGA may not work.

### 2. Configure the connection

The guided setup writes a reusable start script without connecting to the
receiver or caster during setup:

```bash
python -m examples.ntrip_client.setup
```

Enter the full URL, including mountpoint, such as
`http://rtk2go.com:2101/Weinstadt`, then select the protocol, access method,
serial port, baud rate, observation duration and whether to send GGA. For
RTK2go use your **own real email address**, not a placeholder. For a separate
password account the script asks for the password when started unless
`NTRIP_PASSWORD` is already set. It does not write the password to disk.

The wizard creates `ntrip-rover/start.sh` with owner-only permissions and
refuses to overwrite an existing directory. Use `--directory NAME` to create
another configuration. Start the client with:

```bash
./ntrip-rover/start.sh
```

The default run collects a 15-second baseline, then receives corrections for
approximately 60 seconds. The client exits after the configured session and
does not run as a background service.

If the caster disconnects or stops sending corrections, the client retries
within the original session duration. Delays start at one second and double up
to 30 seconds. Use `--reconnect-delay` and `--reconnect-max-delay` to change
those limits. Each connection starts a fresh RTCM decoder and sends a fresh GGA when
available. Authentication and TLS failures stop the run, as do receiver errors.
The reported reconnect count does not measure the complete correction outage.

Add `--reference-check` to query the documented `BASEINFO` log and compare its
valid ECEF position with the most recently received RTCM 1005 or 1006 station
coordinates. The distance is available only while the RTCM station and receiver
query are recent. A change of RTCM station clears the previous result. A small
difference does not prove that the base coordinates or reference frame are
accurate, and the query does not establish when the receiver last updated them.

### Run directly

For a public caster on this same computer, such as the default
[reference-station example](../ntrip_server/README.md), a local test is:

```bash
python -m examples.ntrip_client --port /dev/ttyUSB0 --baud 921600 \
  --caster http://127.0.0.1:2101/BASE01 --ntrip-version 2 \
  --no-gga --baseline-seconds 0 --duration 60 --debug
```

The local base and rover need separate receiver connections because they cannot share
one serial port. Replace the URL and protocol with the provider's details. If
the provider uses a password, provide it without placing it in shell history:

```bash
read -rsp 'Caster password: ' NTRIP_PASSWORD; echo
export NTRIP_PASSWORD
python -m examples.ntrip_client --caster 'https://caster.example.org:443/BASE01' \
  --username YOUR_USERNAME --port /dev/ttyUSB0 --debug
unset NTRIP_PASSWORD
```

The address and username above are placeholders, not a working service. For
RTK2go, use its actual mountpoint, your real email username and NTRIP v1, as the
client uses password `none` if `NTRIP_PASSWORD` is unset. The wizard explicitly
sets `none` for its RTK2go access option. See the [SNIP setup guide](https://www.use-snip.com/newusers/user_setup.html)
and [RTK2go password guidance](https://github.com/tomojitakasu/RTKLIB_bin/issues/28).

## Read the result

The client prints progress and the final summary to standard error. With
`--debug`, it also prints the selected position, message types, correction
age when available, and approximate base-to-rover surface distance if the
stream contains RTCM 1005 or 1006. Treat debug logs as location-sensitive.

| Output | Meaning |
| --- | --- |
| `NTRIP: connected` | The caster accepted the connection without proving that corrections or an RTK fix are available. |
| `RTCM frames` | Number of checksum-valid RTCM messages forwarded to the receiver, not a count of fixes. |
| `SPPNAV` | The receiver's code-based navigation solution. `SINGLE` is standalone, while `PSRDIFF` is a differential code solution. |
| `ADRNAV` | The receiver's carrier-phase navigation solution. `NARROW_FLOAT` is a float solution and `NARROW_INT` is a fixed solution. |
| `selected` | The example chooses between recent SPPNAV and ADRNAV using the receiver's reported horizontal sigma. It is a display selection, not a new position calculation. |
| `sigma` | The receiver's estimated uncertainty, not a measurement of real-world accuracy. A low sigma or fixed solution does not prove that the base coordinates and reference frame are correct. |
| `correction age` | Receiver-reported age in seconds when present. The example excludes ADRNAV differential/RTK results with a reported age over 10 seconds, negative or non-finite age, while an unavailable age is not independently verified. |
| `Precision estimate` | Comparison of average **SPPNAV-reported** sigmas before and after connection. A pre-existing augmented baseline or changing conditions can affect it. |
| `RTK: fixed solution observed` | At least one accepted ADRNAV sample was reported as a fixed type during this run. |

The process exits successfully when at least one RTCM frame was forwarded, while
success does **not** mean an RTK fixed solution was obtained. Verify actual
accuracy against a known point when it matters. Base survey errors, frame and
epoch differences, sky view, multipath and the distance to the base affect the
result. The reported height is ellipsoidal, not height above mean sea level.

## Options

| Option | Default | Meaning |
| --- | --- | --- |
| `--port` | `/dev/ttyUSB0` | Rover serial device. |
| `--baud` | `921600` | Receiver serial baud rate. |
| `--caster` | `https://crtk.net:443/NEAR4` | Full provider URL, including mountpoint. Specify your own service details. |
| `--ntrip-version` | `2` | Protocol version `1` or `2`. |
| `--username` | none | Provider username, omitted for guest access. |
| `--password-env` | `NTRIP_PASSWORD` | Name of an environment variable containing the password. Passwords are not command-line options. |
| `--antenna` | `primary` | Receiver antenna `primary` or `secondary`. |
| `--baseline-seconds` | `15` | Time to collect SPPNAV samples before connection, with `0` skipping it. |
| `--duration` | `60` | Approximate correction-session duration in seconds, including connection setup. |
| `--timeout` | `5` | Connection and receiver timeout in seconds. |
| `--no-gga` | off | Do not send the rover's position to the caster. |
| `--reference-check` | off | Compare recent RTCM station coordinates with valid receiver BASEINFO. |
| `--debug` | off | Print connection, position and RTCM details. |

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| Cannot open serial port | Check the device, baud rate, Linux group permissions, and whether another program holds the port. |
| Connection refused, TLS error or timeout | Check hostname, port, network and whether the provider expects HTTP or HTTPS. For HTTPS, use the hostname on a trusted certificate. |
| Unauthorized or missing stream | Check username, password, mountpoint spelling and NTRIP version. Public services may restrict repeated failed attempts, so check details and wait before retrying. |
| Waiting for GGA or no RTCM | Give the receiver time to acquire a valid fix and check antenna/sky view. If the provider requires GGA, do not use `--no-gga`. |
| Frames forwarded but no fixed solution | Confirm compatible RTCM messages and signals, correction age, base distance, base coordinates, rover settings and satellite visibility. Convergence can take time. |
| Stream ends | The client retries transient disconnections until the session duration expires. Check the network and caster if reconnects continue. Authentication, TLS and receiver errors stop the run. |

The example forwards RTCM3 frames and does not configure or monitor Galileo
E6-HAS or BeiDou PPP-B2b. For receiver PPP diagnostics see [has_b2b_ppp_fix](../has_b2b_ppp_fix/README.md).

## References

[Unicore N4 commands and logs manual](https://en.unicorecomm.com/uploads/file/Unicore%20Reference%20Commands%20Manual%20For%20N4%20High%20Precision%20Products_V2_EN_R1.14.pdf).
