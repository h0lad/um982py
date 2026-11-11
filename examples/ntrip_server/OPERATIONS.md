# Internet operation and relays

See [SURVEY.md](SURVEY.md) for station coordinates and [ACCESS.md](ACCESS.md)
for accounts and certificates.

For a new single station, start with `python -m examples.ntrip_server.setup`.
It creates a reusable `ntrip-station/start.sh`, and the [quick start](README.md#run)
explains the inputs. The options below are for tuning and larger deployments.

## Check the running caster

Only one process may use the receiver's serial port at a time. With a local
receiver, the caster stops the existing logs on that port, switches to fixed
base mode, sets the antenna offset to zero and enables RTCM output. The manifest
must contain ARP coordinates so that the offset is not applied twice. Stopping
the caster does not restore the previous receiver mode or log subscriptions.
Plan for these changes if the receiver is shared with other applications.

Start the generated script and watch its log. After the receiver supplies a
valid base position and recent satellite observations, check readiness on the
same host:

```bash
curl -i http://127.0.0.1:2101/healthz
```

This example uses the wizard's default loopback address and port. For private
mode add `--user rover` and enter the password when prompted. A `200` and
`ready` mean the caster recently received a matching base position and an
observation message. `503` means the source is not ready, while `401` means
credentials are missing or invalid.

For an internet listener use its actual `https://hostname:port/healthz` and a
client that verifies the certificate. The optional status website runs
on a separate port and is described in [STATUS.md](STATUS.md).

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Serial port cannot be opened | Check the device path with `ls -l /dev/ttyUSB*`, the service user's groups with `id`, and whether another process is using the port with `fuser /dev/ttyUSB0`. Only one process can own it. |
| `503 Service Unavailable` | Check the source and logs. The caster needs a recent RTCM 1005 base position and at least one recent observation message before serving a rover. Allow time for satellite reception. |
| `401 Unauthorized` | Check the selected mode and account file, and enter the correct rover credentials. Upload sources use a separate source account. |
| Source rejected or process exits | Check the mountpoint, station ID and ARP coordinates against the source. RTCM 1005 must match the manifest to within 2 cm in ECEF distance. |
| Remote connection fails | Check the bind address, DNS, firewall and port forwarding. For TLS, use the hostname in the certificate and ensure the client trusts its issuer. |
| Data arrives but the rover does not fix | Check rover configuration, common tracked signals, satellite visibility, base survey and correction age. |

## Budgets and deadlines

Each process allows 1024 connections, up to 16 per IP and 32 streams per
account. Each client can queue 32 pending frames. Adjust these limits with
`--max-clients`, `--max-per-ip`, `--max-per-user` and `--queue-frames`. Before
the TLS handshake, admission is limited to 100 connections/s. Password checks
run at up to 4/s, with two parallel scrypt verifications.

TLS handshakes, headers and writes have 5 s deadlines. The caster disconnects
slow clients and closes streams when the source fails. It blocks output after
10 s without observations or 30 s without coordinates. These ages measure time
since reception.

The caster rejects a source whose station ID or position differs from the
manifest. In receiver or upstream relay mode, this can terminate the process.
For an uploaded source, it disconnects the uploader. Monitor `/healthz` and
process restarts from outside the caster.

## Service unit

[`ntrip.service`](ntrip.service) contains a restricted systemd unit. Adapt the
`ntrip` user, `dialout` group, device path, checkout/venv under `/opt/um982py`
and configuration under `/etc/ntrip` to the installation. Set up firewall,
operating-system and upstream connection limits against connection floods.
Check CPU, memory and outbound bandwidth under the expected load.

The example unit explicitly selects private mode and uses paths under
`/opt/um982py` and `/etc/ntrip` rather than automatically using the wizard's
`start.sh`. Create the service account and install or copy the project,
manifest, account file and TLS files to the paths you choose. The service user
must be able to read the mode-0600 files and TLS key and access `/dev/ttyUSB0`
through its serial-device group. In the unit, change `User`, `Group`,
`SupplementaryGroups`, `WorkingDirectory`, `ExecStart` and `DeviceAllow` to
match. For public access explicitly replace `--mode private --users ...` with
`--mode public`, and check the complete command and file permissions first.

After installing the adapted unit, run `systemctl daemon-reload` and
`systemctl enable --now ntrip.service` to start it at boot. Inspect its logs
with `journalctl -u ntrip.service -f`. Measure memory, process and file
descriptor use before setting the unit's limits.

Public and private modes use the same connection, queue, timeout and
authentication limits. Capacity also depends on file descriptors, TLS
termination, firewall limits and network bandwidth. Size these for the
deployment and load-test the intended number of clients.

## Relays

Use one TLS relay per additional process because only one process reads the serial
receiver. Use the same reviewed `station.json` on origin and relays, and create a
dedicated relay account on the origin:

```bash
read -rsp 'Relay password: ' NTRIP_UPSTREAM_PASSWORD
export NTRIP_UPSTREAM_PASSWORD
python -m examples.ntrip_server \
  --station station.json --mode public \
  --upstream-host origin.example.org --upstream-port 2101 --upstream-user relay01 \
  --bind 0.0.0.0 --listen-port 2101 \
  --tls-cert edge-fullchain.pem --tls-key edge-privkey.pem
```

For an internal CA, pass `--upstream-ca ca.pem`. In a service, supply the
password through a protected secret mechanism. Restrict the origin's firewall
to relay connections. TCP load balancers must preserve long streams and source
addresses. The caster does not read `X-Forwarded-For` or PROXY protocol.

## Before release

Run the [client tests](CLIENTS.md), then check the RTCM coordinates and a rover
fix at a known control point with hardware. For the status website, see
[STATUS.md](STATUS.md).
