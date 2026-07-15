# Contributing to OAcquire

Contributions are welcome. The most valuable ones are **new source adapters**
and **failure cases**: if OAcquire misses an open-access PDF that demonstrably
exists, open an issue with the DOI and the `note` code from your report.

## Development setup

```bash
git clone https://github.com/pecesama/oacquire.git
cd oacquire
pip install -e ".[dev]"
pytest          # 29 tests, all offline
pyflakes oacquire/
```

The test suite makes **no network calls**. Source adapters are tested against
recorded API fixtures. Please keep it that way — tests that hit live APIs are
flaky and impolite to the services we depend on.

## The source-adapter contract

A source adapter lives in `oacquire/sources.py` and looks like this:

```python
def find_<source>_pdf(session, identifier, timeout, ...) -> Tuple[str, str]:
    """Return (pdf_url, note). Return ("", reason) when nothing is found."""
```

Adapters must:
1. **Never raise** on an expected failure — return `("", "reason_code")`.
2. **Never bypass a paywall.** Adapters that scrape shadow libraries will be
   rejected. This is not negotiable.
3. **Be polite**: use the shared `session` (which carries retry/backoff), honour
   `timeout`, and respect the upstream service's rate limits and terms.
4. **Emit machine-readable notes**: `snake_case:detail`, so failures aggregate
   cleanly in the audit log.

Register the adapter in `_collect_pdf_candidates()`, add a `--no-<source>` flag
in `cli.py`, add a fixture-based test, and document it in the README table.

## Pull requests

- One logical change per PR; keep the diff readable.
- Add or update tests for behaviour you change.
- Update `CHANGELOG.md` under `[Unreleased]`.
- If you used AI assistance, say so in the PR description (which tools, and for
  what) — this mirrors the disclosure the project makes in its README.

## Reporting a retrieval failure

Open an issue with:
- The DOI/PMID/PMCID
- The `note` column from `download_report.csv`
- The output of `oacquire --version`
- Whether an OA version is listed in Unpaywall (`https://api.unpaywall.org/v2/<DOI>?email=you@x.edu`)

These reports are the single most useful contribution — they are the raw
material for improving the cascade.
