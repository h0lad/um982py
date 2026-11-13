# NTRIP rover client

Use the [sourcetable discovery example](../ntrip_sources/README.md) to inspect
advertised mountpoints before selecting a caster URL.

Connect a UM982 rover to an NTRIP caster and forward RTCM corrections to the
receiver. The client reports the position and RTK solution computed by the
receiver.

For a minimal relay using `RtkSession` and `ReceiverStream`, run
`python -m examples.ntrip_client.managed --help`. Configure rover mode on the
receiver first. That relay does not change or persist receiver settings. The
walkthrough below uses the full client, which includes receiver diagnostics.

Run commands from the repository root after following
[the example installation instructions](../README.md#running-the-examples).

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

This rover example needs no base-station coordinates or antenna H/E/N offsets.
With GGA enabled, the client waits for a valid approximate fix and sends it to
the caster. It updates GGA approximately every 10 seconds.

The caster can see that position. With HTTP, the client sends the position and
any credentials without encryption. Use HTTPS when available.

`--no-gga` disables GGA, but streams requiring it may not work.

### 2. Configure the connection

The guided setup writes a reusable start script without connecting to the
receiver or caster:

```bash
python -m examples.ntrip_client.setup
```

Enter the full URL, including mountpoint, such as
`http://rtk2go.com:2101/Weinstadt`. Select the protocol, access method, serial
port, baud rate, observation duration and whether to send GGA. For RTK2go, use
your **own real email address**, not a placeholder. For a separate password
account, the script asks for the password when started unless `NTRIP_PASSWORD`
is already set. It does not write the password to disk.

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
until the original session ends. Delays start at one second and double up to
30 seconds. Adjust these limits with `--reconnect-delay` and
`--reconnect-max-delay`. Each connection starts a fresh RTCM decoder and sends
a fresh GGA if available.

Authentication, TLS and receiver errors stop the run. The reconnect count alone
cannot measure the full correction outage.

Add `--reference-check` to query `BASEINFO`. The client compares the valid ECEF
position from that log with the latest RTCM 1005 or 1006 station coordinates.
It reports distance only while both the RTCM station data and receiver query
are recent. A station change clears the result. The query does not reveal when
the receiver last updated its reference coordinates.

### Run directly

For a public caster on this same computer, such as the default
[reference-station example](../ntrip_server/README.md), a local test is:

```bash
python -m examples.ntrip_client --port /dev/ttyUSB0 --baud 921600 \
  --caster http://127.0.0.1:2101/BASE01 --ntrip-version 2 \
  --no-gga --baseline-seconds 0 --duration 60 --debug
```

The local base and rover need separate receiver connections. They cannot share
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
| `NTRIP: connected` | The caster accepted the connection. |
| `RTCM frames` | Number of checksum-valid RTCM messages forwarded to the receiver, not a count of fixes. |
| `SPPNAV` | The receiver's code-based navigation solution. `SINGLE` is standalone, while `PSRDIFF` is a differential code solution. |
| `ADRNAV` | The receiver's carrier-phase navigation solution. `NARROW_FLOAT` is a float solution and `NARROW_INT` is a fixed solution. |
| `selected` | The example chooses between recent SPPNAV and ADRNAV using the receiver's reported horizontal RMS. It is a display selection, not a new position calculation. |
| `sigma` | The receiver's estimated uncertainty. |
| `correction age` | Receiver-reported age in seconds when present. The example excludes ADRNAV differential/RTK results with a reported age over 10 seconds, negative or non-finite age, while an unavailable age is not independently verified. |
| `Precision estimate` | Comparison of average **SPPNAV-reported** sigmas before and after connection. A pre-existing augmented baseline or changing conditions can affect it. |
| `RTK: fixed solution observed` | At least one accepted ADRNAV sample was reported as a fixed type during this run. |

Forwarding at least one RTCM frame counts as a successful run, even without an
RTK fixed solution. Reported heights are above the ellipsoid.

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
