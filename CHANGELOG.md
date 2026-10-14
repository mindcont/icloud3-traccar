# Changelog

## 0.1.0-beta.1 — 2026-10-14 preview

- Split the optional iCloud3 Traccar bridge into its own repository.
- Add HACS metadata, English/Chinese installation and configuration guides.
- Retain live in-memory sampling and explicit Recorder history import.
- Use existing HA device_id as Traccar uniqueId with automatic device reuse/creation.
- Include retries, duplicate checks, durable checkpoints and isolated history/live workers.
- Include status/diagnostics redaction and original project brand assets.

The maintainer confirmed real Traccar, browser UI and HACS installation validation
on 2026-10-14. Automated tests and hassfest gate the main-branch pre-release.
