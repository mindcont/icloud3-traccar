# Development

Use a feature branch and synthetic data. Never commit credentials or production HA configuration.

Runtime validation targets Python 3.13 and Home Assistant 2025.3.4:

```sh
python -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-test.txt
python -m compileall -q custom_components/icloud3_traccar tests tests_runtime
python -m unittest discover -s tests -v
python -m unittest discover -s tests_runtime -v
```

Run the suites in separate processes: `tests/` installs explicit HA adapter doubles; `tests_runtime/` imports real HA and creates a temporary SQLite Recorder database. Neither suite needs Apple credentials or production Traccar access. The HTTP suite uses synthetic points and a loopback server, not a real Traccar instance.

Before release, verify a disposable Traccar 6.8.1 server, browser configuration UI, HACS installation, and restart/reload behavior. Mark unexecuted checks as unverified. See `docs/release-checklist.md`.
