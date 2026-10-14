# Preview release checklist

Target version: `v0.1.0-beta.1`. No stable/production claim.

- [x] Separate integration directory only; no copied iCloud3 core.
- [x] Preserve source provenance and MIT copyright.
- [x] Bilingual README, HACS metadata, version and repository URLs.
- [x] Automated HTTP/worker tests and real HA/SQLite Recorder tests included.
- [x] Dedicated CI and scoped hassfest configuration included.
- [x] Original brand icon assets included.
- [x] Confirm standalone branch Actions: 47 behavior tests + 4 real HA/Recorder tests and hassfest passed.
- [x] Real Traccar verification: maintainer confirmed passed on 2026-10-14.
- [x] Browser UI verification: maintainer confirmed passed on 2026-10-14.
- [x] HACS installation verification: maintainer confirmed passed on 2026-10-14.
- [ ] Merge reviewed standalone changes into the default branch.
- [ ] Publish a GitHub pre-release `v0.1.0-beta.1` after the intended validation gates.

Do not silently convert unchecked items into passes or label this a stable release.
No production deployment or database migration is part of the repository split.

Manual validation was reported by the maintainer in this session; environment details and raw browser/server evidence were not supplied. Merge/publication completion is verified through GitHub after execution.
