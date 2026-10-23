# Settings

For a guided first setup, run `python -m examples.ntrip_server.setup`. It
creates a station manifest, any needed account files, and a start script. Use
the settings below when you want to configure or tune the server manually.

Every option with its default and requirement level. `required` means the
process or the survey refuses to start without it, `conditional` names the mode
that requires it, `optional` always has the listed default.

## Receiver and capture

| Option | Default | Level | Note |
| --- | --- | --- | --- |
| `--port` | `/dev/ttyUSB0` | optional | Serial device claimed by the process. |
| `--baud` | `921600` | optional | Serial baud rate. |
| `--timeout` | `3.0` | optional | I/O timeout in seconds. |
| `--antenna` | `primary` | optional | `primary`/`1` only. The caster and the survey reject ANT2. |
| `--replay` | none | optional | Read captured bytes instead of the device. With `--station` this validates RTCM offline and then exits. |
| `--json` | none | optional | Write a result file. Only for the offline RTCM check. |
| `--record` | none | optional | Save received wire bytes in survey mode without overwriting an existing file. |

## Station and accounts

| Option | Default | Level | Note |
| --- | --- | --- | --- |
| `--station` | none | required | Reviewed ARP manifest with `position_verified` already set to `true`. |
| `--mode` | legacy behavior | optional | `public` enables guest rovers, while `private` requires accounts, protects sourcetable access and keeps the status site on loopback. |
| `--users` | none | required for private access, optional for public | `0600` JSON of rover username to password hash. The wizard creates it for private mode. |
| `--source-users` | none | optional | `0600` JSON of source-only credentials, enabling incoming source mode in place of the receiver. The v1 source password uses the username `source`. Cannot be combined with `--upstream-host`. |
| `--public` | off | optional | Allows guest GET without a user file. |
| `--hash-password` | off | optional | Prints one hash and exits, ignoring all other options. |

## Listener and TLS

| Option | Default | Level | Note |
| --- | --- | --- | --- |
| `--bind` | `127.0.0.1` | optional | Caster address. |
| `--listen-port` | `2101` | optional | `1..65535`. |
| `--tls-cert` | none | conditional | Required for a non-loopback `--bind`, together with `--tls-key`. |
| `--tls-key` | none | conditional | Required with `--tls-cert`. |

A non-loopback listener without both files is an error, not a warning.

## Connection budgets

| Option | Default | Level | Note |
| --- | --- | --- | --- |
| `--max-clients` | `1024` | optional | Connections per process. |
| `--max-per-ip` | `16` | optional | Connections per source address. |
| `--max-per-user` | `32` | optional | Streams per account. |
| `--queue-frames` | `32` | optional | Pending frames per client before it counts as slow. |

## Relay

| Option | Default | Level | Note |
| --- | --- | --- | --- |
| `--upstream-host` | none | optional | Setting it switches from receiver to relay mode. |
| `--upstream-port` | `443` | optional | `1..65535`. |
| `--upstream-user` | none | conditional | Required with `--upstream-host`. |
| `--upstream-ca` | none | optional | Extra CA file for a private origin. |
| `NTRIP_UPSTREAM_PASSWORD` | unset | conditional | Environment variable, required with `--upstream-host` and never a flag. |

## Status website

| Option | Default | Level | Note |
| --- | --- | --- | --- |
| `--status-port` | off | optional | Setting it enables the website. |
| `--status-bind` | `127.0.0.1` | optional | Non-loopback binds need the caster TLS files. |
| `--status-caster-url` | none | conditional | Public HTTPS origin including port, required with `--status-port`. |
| `--status-contact-url` | none | optional | ASCII HTTPS page for access requests. |
| `--status-max-clients` | `64` | optional | Status budget, separate from the caster. |
| `--status-per-ip` | `8` | optional | Must satisfy `1 <= per-ip <= clients <= 4096`. |

## Station survey

`--survey-output` switches the process to survey mode, and the metadata rows below
are then required, because a RINEX header without them would be ambiguous.

| Option | Default | Level | Note |
| --- | --- | --- | --- |
| `--survey-output` | off | optional | New RINEX file, enabling survey mode. |
| `--seconds` | `86400` | optional | At most `172800` (48 h). |
| `--interval` | `30` | optional | At least 15 s. |
| `--marker-name` | `UM982` | optional | RINEX marker name. |
| `--antenna-type` | none | required in survey mode | IGS antenna and radome code, 1..20 ASCII characters. Use an honest `UNKNOWN ... NONE` when the antenna is not calibrated rather than inventing a code. |
| `--antenna-serial` | none | required in survey mode | 1..20 ASCII characters. |
| `--receiver-serial` | none | required in survey mode | 1..20 ASCII characters. |
| `--receiver-firmware` | none | required in survey mode | 1..20 ASCII characters. |
| `--approx-position` | none | required in survey mode | Approximate marker position as Earth-centred X, Y and Z in metres, used in the RINEX file header. See [rough position](SURVEY.md#2-obtain-a-rough-position). |
| `--antenna-hen` | none | required in survey mode | Three measured distances in metres **from marker to antenna reference point**, in height/east/north order. Height is vertical and non-negative (`0..100`), while east and north are signed (`-100..100`). [How to measure them](SURVEY.md#what---antenna-hen-h-e-n-means). |
| `--l2c-code` | none | optional | `2S`, `2L` or `2X` for a known type-9 L2C, leaving omitted values unreported. |

## Station manifest

`station.example.json` is the template. Required fields:

| Field | Constraint |
| --- | --- |
| `mountpoint` | 1..64 letters, digits, `_` or `-`, with `healthz` reserved. |
| `station_id` | Integer `0..4095`, identical in RTCM 1005. |
| `latitude`, `longitude` | Degrees, `-90..90` and `-180..180`, ARP not marker. |
| `height` | Ellipsoidal ARP height in metres, `-1000..10000`. |
| `reference_frame` | 1..512 characters naming the published frame. |
| `coordinate_epoch` | `1980..2100`. |
| `source_report` | 1..512 characters naming the reviewed solution. |
| `position_verified` | Must be `true`, but the template ships with `false`. |

Optional fields:

| Field | Default | Note |
| --- | --- | --- |
| `reference_point` | `ARP` | Only `ARP` is accepted. |
| `country` | `DEU` | Three uppercase letters, used in the sourcetable. |
| `carrier` | `2` | Sourcetable carrier profile: `0` no carrier phase, `1` single-frequency, `2` dual-frequency. Set from the actual receiver configuration. |
| `bitrate` | `9600` | Estimated sourcetable data rate in bits per second, so measure the stream and update this value for your station. |

No other field is accepted: unknown keys fail the load with a `ValueError`.
