# NTRIP sourcetable discovery

List a caster's advertised mountpoints, optionally ordered by great-circle
distance from a rover position:

```sh
python -m examples.ntrip_sources https://caster.example:443 --position 50.0 8.0
```

For authenticated casters, set `NTRIP_PASSWORD` and pass `--username`. The
caster may require a different NTRIP version, selected with `--version`.
An advertised location can be absent, approximate or unsuitable for a virtual
reference station. Check the format, coverage, service requirements and
licence before choosing a mountpoint.
