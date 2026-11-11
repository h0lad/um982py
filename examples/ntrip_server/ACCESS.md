# Access and TLS

Choose who can read the correction stream and how clients connect. A rover
reads the stream. A source supplies base data, either from the local receiver
or through an upload. Rover and source accounts use separate credentials.

## Accounts

The [setup wizard](README.md#run) creates the account files and hashes for you.

Use `--mode public` for guest access. If there are no accounts, omit `--users`.
Guests leave the username and password empty. The caster rejects incorrect
non-empty credentials even in public mode. Connection and buffer limits also
apply to guests. The bind address and firewall control network access in both
modes.

Use `--mode private --users users.json` for an authenticated service, including
access to the sourcetable. Private mode binds the unauthenticated status site to
loopback only, so protect any proxy used to expose it. Both modes allow non-loopback
caster listeners with TLS. Private mode is the default.

Private mode does not create a VPN or IP allowlist. Where practical, create a
separate account for each rover. Each rover needs its username, password,
caster hostname, port and mountpoint.

Only the service user may read the account file. Its JSON values contain
password hashes. To add or remove an account, edit the file and restart the
server. The wizard creates the first private rover account and its hash.

To add an account to an existing wizard setup:

1. Run `python -m examples.ntrip_server --hash-password` and enter the new
   password at the hidden prompt. The password must be 16–256 UTF-8 bytes.
2. Add the username and complete printed hash as another JSON entry in
   `ntrip-station/users.json`, for example `"rover2": "scrypt$..."`. Preserve
   existing entries and JSON commas. Replace `...` with the complete hash.
3. Keep permissions at `0600`, restart the caster, and give the new user their
   username and password through an appropriate secure channel. The caster
   stores only the hash and cannot recover a forgotten password.

To accept uploads in place of a serial receiver, pass
`--source-users source-users.json`. This file uses the same protected JSON and
scrypt-hash format as `--users`, with separate credentials. NTRIP v2 sources
use a username and password from the source file. NTRIP v1 uses the password of
the `source` account. Only one source can connect at a time.

An upload must match the configured mountpoint, station ID and surveyed ARP.
When the source disconnects, the caster invalidates it and closes rover streams.
Use TLS for remote source connections, or a trusted local TLS gateway for a
source tool that lacks TLS. `--source-users` and `--upstream-host` are mutually
exclusive. Do not reuse rover credentials for source access.

Generate a hash with `python -m examples.ntrip_server --hash-password`, then
put it in a mode-0600 file containing a JSON object such as
`{"source": "scrypt$..."}`. Use the complete generated hash in place of the
ellipsis. Start the source-enabled caster on loopback for a local source:

```bash
python -m examples.ntrip_server --station station.json --mode public \
    --source-users source-users.json --bind 127.0.0.1 --listen-port 2101
```

Configure the external source to emit the profile and ARP in the station
manifest. Upload mode does not configure a receiver.

## Transport security

External listeners require TLS ≥1.2 with a trusted certificate matching the DNS
name. Plaintext is allowed on numeric loopback addresses only. Legacy clients
without TLS need a local TLS/VPN gateway. Protect key and user file with mode
0600 and run the service without root privileges. Changes to certificates, users
or coordinates require a restart, after which rovers reconnect.

`--bind 127.0.0.1` listens only on this computer. `--bind 0.0.0.0` listens on
all IPv4 interfaces and requires `--tls-cert` and `--tls-key`. Configure DNS,
the firewall and port forwarding separately. The wizard checks that it can load
the certificate and key. You must arrange their issuance, renewal and
permissions.

## Exposure

Correction streams carry the precise base coordinate. The sourcetable at `/`
contains a rounded position. In private mode, reading it requires credentials.
`/healthz` returns 200 for current observations and a matching reference
position, or 503 if the source is not ready. Private mode also requires
credentials for this endpoint.

Continue with [internet operation and relays](OPERATIONS.md).
