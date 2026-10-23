# Internet operation and relays

See [SURVEY.md](SURVEY.md) for station coordinates and [ACCESS.md](ACCESS.md)
for accounts and certificates.

For a new single station, start with `python -m examples.ntrip_server.setup`.
It creates a reusable `ntrip-station/start.sh`, and the [quick start](README.md#run)
explains the inputs. The options below are for tuning and larger deployments.

## Check the running caster

Only one process may use the receiver's serial port at a time. When started
with a local receiver, the caster stops existing logs on the
connected serial port, switches the receiver to fixed base mode, sets its
antenna offset to zero, and enables the RTCM outputs. The manifest must already
contain the ARP coordinates, so an offset is not applied twice. These are
receiver configuration changes, and stopping the caster does not automatically
restore the previous receiver mode or log subscriptions. Plan for this if the
receiver is shared with other applications.

Start the generated script and watch its log. After the receiver supplies a
valid base position and recent satellite observations, check readiness on the
same host:

```bash
curl -i http://127.0.0.1:2101/healthz
```

This example uses the wizard's default loopback address and port. For private
mode add `--user rover` and enter the password when prompted. A `200` and
`ready` mean the caster recently received a matching base position and an
observation message. `503` means the source is not ready, while `401` means credentials
are missing or invalid. Readiness does not establish the absolute accuracy of
the base or prove that a rover has a fixed RTK solution.

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
| Data arrives but the rover does not fix | Check rover configuration, common tracked signals, satellite visibility, base survey and correction age. A successful network connection alone cannot guarantee an RTK fix. |

## Budgets and deadlines

Default budgets per process: 1024 connections, 16 per IP, 32 streams per
account, 32 pending frames per client. Adjustable with `--max-clients`,
`--max-per-ip`, `--max-per-user`, `--queue-frames`. Admission before the TLS
handshake is limited to 100 connections/s, password checks to 4/s with two
parallel scrypt verifications. TLS handshake, headers and writes have 5 s
deadlines. Slow clients are disconnected. Streams are closed when the source
fails, and missing observations after 10 s and coordinates after 30 s block the
output. Freshness refers to reception time. A mismatched station ID or position
rejects the source, which in receiver or upstream relay mode can terminate the
process, while an uploaded source is disconnected. Monitor `/healthz` and
process restarts externally.

## Service unit

[`ntrip.service`](ntrip.service) contains a restricted systemd unit. Adapt the
`ntrip` user, `dialout` group, device path, checkout/venv under `/opt/um982py`
and configuration under `/etc/ntrip` to the installation. Set up firewall,
operating-system and upstream connection limits against connection floods.
Resource budgets do not replace capacity measurement, so check CPU, RAM and egress
against the actual data rates.

The example unit explicitly selects private mode and uses paths under
`/opt/um982py` and `/etc/ntrip` rather than automatically using the wizard's
`start.sh`. Create the service account and install or copy the project,
manifest, account file and TLS files to the paths you choose. The service user
must be able to read the mode-0600 files and TLS key and access `/dev/ttyUSB0`
through its serial-device group. In the unit, change `User`, `Group`,
`SupplementaryGroups`, `WorkingDirectory`, `ExecStart` and `DeviceAllow` to
match. For public access explicitly replace `--mode private --users ...` with
`--mode public`, and check the complete command and file permissions first.

After installing the adapted unit, use `systemctl daemon-reload`,
`systemctl enable --now ntrip.service` and `journalctl -u ntrip.service -f` to
start it at boot and inspect its logs. The unit's memory, process and file
descriptor limits are examples to measure for your deployment.

The public and private modes use the same connection, queue, timeout and
authentication budgets. These limits reduce exposure to slow clients and
connection floods without guaranteeing capacity or resistance to every
attack. Size file-descriptor limits, TLS termination, firewall limits and network
bandwidth for the deployment, then load-test the intended number of clients.

## Relays

Use one TLS relay per additional process because only one process reads the serial
receiver. Use the same reviewed `station.json` on origin and relays, and create a
dedicated relay account on the origin:

```bash
read -rsp 'Relay password: ' NTRIP_UPSTREAM_PASSWORD
export NTRIP_UPSTREAM_PASSWORD
python -m examples.ntrip_server \
  --station station.json --public \
  --upstream-host origin.example.org --upstream-port 2101 --upstream-user relay01 \
  --bind 0.0.0.0 --listen-port 2101 \
  --tls-cert edge-fullchain.pem --tls-key edge-privkey.pem
```

For an internal CA pass `--upstream-ca ca.pem`. Under the service, set the
password through a protected secret mechanism. Restrict the origin to relays via
firewall. TCP load balancers must preserve long streams and source addresses because
`X-Forwarded-For` and PROXY protocol are not evaluated.

## Before release

[Clients and tests](CLIENTS.md). Also verify the RTCM coordinates and a rover fix
at a known control point using hardware. The status website is documented in
[STATUS.md](STATUS.md).
