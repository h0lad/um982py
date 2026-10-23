# NTRIP clients

A client needs a hostname, port, mountpoint and, for private mode, a rover
username and password. With the wizard defaults the caster is reachable only on
the same computer at `127.0.0.1:2101`, and the default mountpoint is `BASE01`.
Wait until `/healthz` reports ready before testing the stream.

For a quick local **public mode** connection check, run this in another
terminal while the caster is running:

```bash
curl --fail --no-buffer --max-time 10 \
  -H 'Ntrip-Version: Ntrip/2.0' \
  http://127.0.0.1:2101/BASE01 -o corrections.rtcm
```

The file contains binary RTCM messages, not human-readable text. This is an
ongoing stream, so curl stops with a timeout after 10 seconds, and a non-empty file
indicates data was received, not that a rover achieved an RTK fix. For private
mode add `--user rover` to prompt for the password. Replace `rover` with the
configured username. For a remote caster, use its `https://hostname:port/BASE01`
URL and a trusted certificate matching the hostname.

These client implementations were exercised with the caster:

| Download | Tested version | Protocol / transport |
| --- | --- | --- |
| [RTKLIB str2str](https://github.com/tomojitakasu/RTKLIB) | 2.4.2 p13 | NTRIP v1, TCP |
| [BKG POSIX ntripclient](https://igs.bkg.bund.de/root_ftp/NTRIP/software/ntripclient.zip) | source revision 1.50 | NTRIP v1/v2, TCP |
| [pygnssutils](https://github.com/semuconsulting/pygnssutils) | 1.2.8 | NTRIP v1/v2, TCP/TLS |
| [BKG Ntrip Client (BNC)](https://igs.bkg.bund.de/ntrip/bnc) | 2.13.7 | NTRIP v1/v2, TCP |

For internet access, use a client with TLS and hostname verification enabled.

The listed RTKLIB and BKG versions need a trusted local TLS gateway.

For pygnssutils guest access, explicitly pass `--ntripuser '' --ntrippassword ''`
to override its placeholder credentials. Use the host, port and mountpoint from
the status page or `station.json`.

After building/downloading the clients separately, run from the development
checkout with OpenSSL installed:

```bash
export NTRIP_STR2STR=/path/to/str2str
export NTRIP_BKG_CLIENT=/path/to/ntripclient
export NTRIP_PYGNSS_CLIENT=/path/to/gnssntripclient
export NTRIP_BNC=/path/to/bnc
export NTRIP_BKG_SERVER=/path/to/ntripserver
python -m pytest tests/examples/test_ntrip_bnc.py tests/examples/test_ntrip_clients.py tests/examples/test_ntrip_filter.py tests/examples/test_ntrip_upload.py tests/examples/test_ntrip_server.py tests/examples/test_ntrip_status.py -q
```
