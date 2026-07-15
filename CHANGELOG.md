# Changelog

All notable changes to this project are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/); versioning follows [SemVer](https://semver.org/).

## [2.0.0] — 2026-07-12

Renamed from `open_pdf_downloader` to **OAcquire**, reflecting what the tool
actually is: an acquisition layer for research pipelines, not a download script.

### Added
- Installable package (`pip install oacquire`) with an `oacquire` console script.
- Public API surface via `oacquire/__init__.py` (`retrieve_pdf`, `build_session`,
  `DownloadResult`, `DiscoveryConfig`).
- Offline test suite (29 tests, no network access) and CI across
  Linux/macOS/Windows × Python 3.9/3.11/3.12.
- `--version` and `--citation` flags; the canonical citation is now emitted by
  the tool itself.
- `CITATION.cff` with a `preferred-citation` block.
- `CONTRIBUTING.md` documenting the source-adapter contract.

### Changed
- **BREAKING:** module renamed `open_pdf_downloader` → `oacquire`. The old
  import path still works via a deprecation shim and will be removed in v3.0.0.
- Monolithic 1,296-line module split along its existing layer boundaries into
  `config` / `http` / `parsing` / `sources` / `core` / `cli`.
- `DownloadResult` fields now have defaults; constructing one no longer requires
  all ten positional arguments. The CSV report schema is unchanged.

### Migration
```python
# before
from open_pdf_downloader import retrieve_pdf
# after
from oacquire import retrieve_pdf
```
```bash
# before
python open_pdf_downloader.py --input lit.csv
# after
oacquire --input lit.csv
```

## [1.1] — 2026-04-17
- Streamlit web interface; fixes to the candidate cascade.

## [1.0] — 2026-04-16
- Initial release: seven-source cascade, CLI, CSV audit log.
