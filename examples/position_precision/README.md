# Map position precision

Match GGA positions with GST receiver-reported error statistics and produce
GeoJSON with east, north and vertical deviations and the reported horizontal
error ellipse. Verify the receiver is configured for WGS 84 before mapping.

```bash
python -m examples.position_precision --port /dev/ttyUSB0 --baud 921600 \
    --reference-frame WGS84 --duration 30 --geojson /tmp/positions.geojson
python -m examples.position_precision --replay tests/fixtures/position-precision.txt \
    --reference-frame WGS84 --geojson /tmp/precision.geojson
python -m examples.position_precision --replay tests/fixtures/position-precision.txt \
    --antenna 2 --reference-frame WGS84
```

GST and GGA contain UTC time of day but no date. Use a short capture from the
same receiver session; matching time alone cannot distinguish different days.
The example matches exactly on time and antenna and does not attach ambiguous
duplicates. An unmatched fix has `"precision": null` in the GeoJSON. An exit
status of 1 means no fix had matched position precision.

The ellipse and deviations are receiver estimates, not independently verified
accuracy or a 95% confidence region. GST's pseudorange RMS is retained separately
and is not a position accuracy radius. The example does not infer correlations.

Reference: Unicore N4 GGA and GST message definitions.
