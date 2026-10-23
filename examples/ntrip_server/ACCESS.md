# Access and TLS

Choose who can read the correction stream and how clients connect securely.
A **rover** is a receiver consuming the stream. A **source** is the local base
receiver or a separate program uploading the base data. These are different
roles with separate credentials. The [setup wizard](README.md#run) asks the
questions and writes the necessary files.

## Accounts

The [setup wizard](README.md#run) creates the account files and hashes for you.

Use `--mode public` for guest access and omit `--users` when there are no accounts.
Guests leave username and password empty. Wrong non-empty credentials are
rejected even with public access. Guests are subject to the same connection and
buffer limits. Public describes access to the corrections, while network exposure
still depends on the bind address and firewall.

Use `--mode private --users users.json` for an authenticated service, including
access to the sourcetable. Private mode binds the unauthenticated status site to
loopback only, so protect any proxy used to expose it. Both modes allow non-loopback
caster listeners with TLS. The legacy `--public` switch still enables guest
access, while omitting both `--mode` and `--public` preserves the earlier
behavior: authenticated streams with a public sourcetable.

Private mode allows remote users if you expose the TLS listener, but does not
automatically set up a VPN or IP allowlist. Create a distinct account for each
rover where practical. A rover connects using its username and password, the
caster hostname and port, and the mountpoint. Keep the account file readable by
the service user only. Its JSON values are password hashes, not plaintext
passwords, and adding or removing accounts requires updating the file and restarting
the server. The wizard creates the first private rover account and its hash.

To add an account to an existing wizard setup:

1. Run `python -m examples.ntrip_server --hash-password` and enter the new
   password at the hidden prompt. The password must be 16–256 UTF-8 bytes.
2. Add the username and complete printed hash as another JSON entry in
   `ntrip-station/users.json`, for example `"rover2": "scrypt$..."`. Preserve
   existing entries, JSON commas and the complete hash, replacing the placeholder `...`.
3. Keep permissions at `0600`, restart the caster, and give the new user their
   username and password through an appropriate secure channel. The caster
   stores only the hash and cannot recover a forgotten password.

To accept a source upload instead of connecting to the serial receiver, supply
`--source-users source-users.json`. This file has the same protected JSON and
scrypt-hash format as `--users`, but is a separate set of credentials. NTRIP v2
sources authenticate with a username and password from the source file, whereas NTRIP v1
uses the password belonging to the `source` account. Only one source may be
connected at a time. An upload must match the configured mountpoint, station ID
and surveyed ARP, and a disconnect invalidates the source and closes rover streams.
Use TLS for remote source connections, or a trusted local TLS gateway for a
source tool that lacks TLS. `--source-users` and `--upstream-host` are mutually
exclusive. Do not reuse rover credentials for source access.

Generate a hash with `python -m examples.ntrip_server --hash-password`, then
put it in a mode-0600 file containing a JSON object such as
`{"source": "scrypt$..."}`. Use the complete generated hash in place of the
ellipsis. Start the source-enabled caster on loopback for a local source:

```bash
python -m examples.ntrip_server --station station.json --public \
    --source-users source-users.json --bind 127.0.0.1 --listen-port 2101
```

The external source must be configured to emit the profile and ARP recorded in
the station manifest. This mode does not configure a receiver itself.

## Transport security

External listeners require TLS ≥1.2 with a trusted certificate matching the DNS
name. Plaintext is allowed on numeric loopback addresses only. Legacy clients
without TLS need a local TLS/VPN gateway. Protect key and user file with mode
0600 and run the service without root privileges. Changes to certificates, users
or coordinates require a restart, after which rovers reconnect.

For example, `--bind 127.0.0.1` listens only on this computer. `--bind 0.0.0.0`
listens on all IPv4 interfaces and therefore requires `--tls-cert` and
`--tls-key`. The certificate must match the DNS name that clients use because merely
enabling TLS does not create DNS, open a firewall, or set up port forwarding.
The wizard validates that the certificate and private key can be loaded, but
you must arrange their issuance, renewal and permissions.

## Exposure

Public streams carry the precise base coordinate. Even with private access the
sourcetable at `/` shows a rounded position unless private mode is selected.
`/healthz` returns 200 for current
observations and a matching reference position, otherwise 503, and for private
access it requires credentials.

Continue with [internet operation and relays](OPERATIONS.md).
