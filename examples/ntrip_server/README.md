# NTRIP reference station

Use a fixed UM982 as a base station and serve its data to rover receivers over
the network. An NTRIP caster is the server, and a mountpoint is the stream a
rover selects.

Keep the antenna fixed at a known position. An error in the base coordinates
can propagate into rover positions even with an RTK fixed solution. Follow
[SURVEY.md](SURVEY.md) to determine and review the base position.

## Run

Run the commands from the repository root. Install the project and
its serial dependency as described in [running the examples](../README.md#running-the-examples).

For a new base station, follow the [step-by-step survey](SURVEY.md):

1. Install the antenna and measure its offsets from a fixed marker.
2. Use the receiver to obtain an approximate position.
3. Record 24 hours and export RINEX, then repeat on an independent day.
4. Upload each RINEX file to Canada's online CSRS-PPP service, review and
   compare its results, and obtain the final coordinates, frame and epoch.
5. Enter the reviewed result into the guided setup below and start the caster.

If you already have a reviewed position for this antenna, start here:

```bash
python -m examples.ntrip_server.setup
```

Choose public or private access and enter the reviewed, surveyed antenna
reference point (ARP). The wizard creates `ntrip-station/station.json`, any
required account files, and `ntrip-station/start.sh`. Start it with:

```bash
./ntrip-station/start.sh
```

Keep the process running while rovers need corrections. By default, the caster
listens locally at `127.0.0.1:2101` with mountpoint `BASE01`. For access from
another machine, select `internet` in the wizard and supply a TLS certificate
and key. Configure DNS, the firewall and port forwarding for your network.

A remote client needs the hostname, port and mountpoint. In private mode, it
also needs a rover username and password.

Use `--directory` to set up another station. The wizard does not overwrite an
existing directory.

### What to have ready

Enter surveyed coordinates for the fixed base antenna. The wizard asks whether
they describe the antenna reference point (ARP) or a ground marker. For marker
coordinates, it applies your measured offsets to calculate the ARP. Coordinates
from the rover, a nearby NTRIP station or a rough receiver fix cannot replace
the reviewed base survey.

| Input | What to enter |
| --- | --- |
| Mountpoint | A name you choose for the stream, such as `BASE01`. Clients use it to connect. |
| RTCM station ID | A number from 0 to 4095. Choose one distinct from nearby bases, or for an uploaded source use its existing RTCM station ID. |
| Latitude and longitude | Surveyed ARP or marker coordinates in decimal degrees. North and east are positive, while south and west are negative. |
| Ellipsoidal height | Surveyed height in metres above the reference ellipsoid, for the same point. It is not height above mean sea level. |
| Marker offsets, if applicable | Measured vertical, east and north distances in metres from marker to ARP. The wizard calculates the ARP. |
| Reference frame and coordinate epoch | The realization and decimal-year epoch stated in the reviewed survey or PPP report, for example `ITRF2020` and `2026.8`. The library does not transform between frames or epochs. |
| Survey report or source | A name or path identifying the reviewed result and field notes. |
| Receiver port or source credentials | For a connected UM982, its serial port, usually `/dev/ttyUSB0`. For uploaded RTCM, the source must use the same station ID and ARP. |
| Access and network | Choose public or private rovers, local or internet access, a port, and, for internet access, an existing TLS certificate and matching private key. Private access also needs a rover username and password. |

If you do not have a reviewed survey, select `not-yet` in the wizard and follow
[the survey steps](SURVEY.md). The library records observations, exports RINEX
and converts marker coordinates to the ARP. An external PPP service or surveyor
must supply and review the absolute position.

For manual configuration, copy `station.example.json` to `station.json` with
surveyed ARP values and set `position_verified` to `true`. Without a certificate,
the server listens on loopback addresses only.

Connect to a receiver:

```bash
python -m examples.ntrip_server --mode private --station station.json --users users.json \
    --port /dev/ttyUSB0 --baud 921600 --bind 0.0.0.0 --listen-port 2101 \
    --tls-cert fullchain.pem --tls-key privkey.pem
```

Use `--mode public` instead of `--mode private --users users.json` for a free
public rover stream. Both modes require TLS on non-loopback listeners. Private
mode requires rover accounts, protects the sourcetable, and restricts the
unauthenticated status website to loopback. Source uploads always require a
separate source account in either mode.

Details: [SURVEY.md](SURVEY.md), [SETTINGS.md](SETTINGS.md),
[ACCESS.md](ACCESS.md), [OPERATIONS.md](OPERATIONS.md), [CLIENTS.md](CLIENTS.md),
and [STATUS.md](STATUS.md).

## How it works

The caster serves RTCM, a binary GNSS data format. Message 1005 contains the
base antenna position every 5 seconds. Messages 1074, 1094 and 1124 carry GPS,
Galileo and BeiDou observations every second. A rover must support the
messages and signals it needs. The station uses one mountpoint and supports
NTRIP v1/v2 over TCP, with TLS for remote access.

The receiver computes observations. The caster selects RTCM frames, checks
their station ID and 1005 coordinates, then forwards them. It does not solve
RTK or independently validate MSM observation values. The receiver's signal
group, configuration and tracking conditions determine which signals enter
MSM4.

Galileo E6 and BeiDou B2 observations do not contain the Galileo HAS or BeiDou
PPP-B2b correction messages. This caster does not publish those PPP services.

The caster supports NTRIP v1/v2 HTTP clients for one station, SOURCE/POST uploads
and the documented TLS relay. Its sourcetable contains one STR record and
supports wildcard, logical and numeric field filters. RTSP/RTP/UDP transports
are unavailable. The interoperability tests do not certify full RTCM conformance.

## Terminology

| Term | Meaning here |
| --- | --- |
| Marker | A fixed, identifiable point on the ground or mounting structure. |
| ARP | Antenna reference point: a manufacturer-defined physical point on the antenna. The base coordinates supplied to the caster refer to this point. |
| H/E/N | Height, east and north distances from the marker to the ARP, in metres. See the [measurement examples](SURVEY.md#what---antenna-hen-h-e-n-means). |
| ECEF | Earth-centred X/Y/Z coordinates in metres. The recording uses an approximate ECEF position in its RINEX header. |
| Ellipsoidal height | Height above the mathematical reference ellipsoid, which differs from height above mean sea level. |
| Frame and epoch | The coordinate system realization and reference date associated with a position. Copy both from the reviewed report and match the rover project. |
| RINEX | A standard file containing recorded satellite observations for later processing. |
| PPP | Precise point positioning: a processing method that uses recorded observations and precise satellite products to estimate a position. |
| RTK | A rover positioning method that uses base observations and carrier-phase measurements, where `fixed` describes the rover solution, not a survey of the base. |
| Sourcetable | A list published by the caster describing its mountpoint and stream. Private mode requires credentials to read it. |

## References

- RTCM 10403.3.
- RTCM 10410.0 and 10410.1, NTRIP 1.0 and 2.0.
- Unicore N4 R1.4 interface guide.
