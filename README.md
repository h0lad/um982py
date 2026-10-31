# um982py

`um982py` is a Python client for Unicore UM982 GNSS receivers. 

UM980 and UM960 are untested but might work.

It requires Python 3.12 or later.


## Installation

```bash
python -m pip install .
```

## Quick start

```python
from um982py import Receiver
from um982py.commands import Log

with Receiver.serial("/dev/ttyUSB0", 921600) as receiver:
    print(receiver.version())
    print(receiver.execute(Log.SATSINFO.read(binary=True)))
```

```python
from um982py.messages.qzss_dcr import decode_qzqsm

report = decode_qzqsm(Log.QZQSM.decode(sentence))
print(report.classification, report.category, report.version)
if report.weather is not None:
    print(report.weather.information_type, report.weather.regions)
```
```python
from um982py.messages.gps_health import GpsLnavHealth, gps_visible_health

health = GpsLnavHealth.from_record(gpseph_record)
print(health.prn, health.navigation_data_ok, health.signal_status)
print(gps_visible_health(satellite_record))  # (PRN, healthy), for GPS entries
```

```python
from um982py.rinex import RinexMetadata, export_rinex

metadata = RinexMetadata(
    receiver_type="UM982",
    receiver_version="your receiver identification",
    antenna_type="your antenna type",
    position_xyz=(x_m, y_m, z_m),
    antenna_delta_hen=(height_m, east_m, north_m),
)
result = export_rinex(records, marker_name="station name", metadata=metadata)
```

The CLI accepts a serial port or a transparent TCP-to-UART gateway:

```bash
um982py --port /dev/ttyUSB0 --baud 921600 version
um982py --port tcp://192.0.2.10:4001 doctor
```
## Development

```bash
python -m pip install -e '.[dev]'
ruff check .
ruff format --check .
python -m mypy
python -m pytest
```

To run hardware tests against a receiver:

```bash
python -m pytest tests/hardware --hardware-port /dev/ttyUSB0 --hardware-baud 921600
```

# License 

EUPL-1.2