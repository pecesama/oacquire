# OAcquire

**A Multi-Source Corpus Acquisition Layer for Agentic Systematic Reviews**

[![PyPI](https://img.shields.io/pypi/v/oacquire.svg)](https://pypi.org/project/oacquire/)
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.21367806.svg)](https://doi.org/10.5281/zenodo.21367806)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/pecesama/oacquire/blob/main/LICENSE)

> **🌐 Try it in your browser — no installation:** **[oacquire.streamlit.app](https://oacquire.streamlit.app)**

---

Screening a systematic review is a solved problem. *Getting the full texts* is not.

Between a completed search (Scopus, OpenAlex, PubMed) and any downstream analysis — manual synthesis, text mining, or an LLM ingestion pipeline — sits an unglamorous, error-prone, and almost entirely undocumented step: turning a list of identifiers into a directory of validated full-text PDFs. In practice this is done by hand, by ad-hoc scripts, or by tools that quietly bypass paywalls. None of these produce a record you can report in a PRISMA flow diagram.

**OAcquire is the acquisition layer for that gap.** It resolves DOIs, PMIDs, and PMCIDs to *legally retrievable* open-access full texts by cascading across seven independent sources, validating every candidate document, and emitting an auditable retrieval log. It is designed to be called three ways: by a human at a command line, by a non-technical researcher in a browser, and — the case it was actually built for — by an autonomous agent as a single typed function call.

## Why this exists

Existing tools fail research workflows in one of three ways:

| | Legal | Multi-source | Auditable log | Agent-callable |
|---|---|---|---|---|
| Manual download | ✅ | — | ❌ | ❌ |
| Reference-manager "find PDF" | ✅ | Partial | ❌ | ❌ |
| Scraping tools with Sci-Hub backends | ❌ | ✅ | ❌ | Partial |
| **OAcquire** | **✅** | **✅ (7 sources)** | **✅** | **✅** |

OAcquire **does not** and **will not** circumvent paywalls. Coverage is bounded by what is legitimately open access — and quantifying exactly where that boundary falls, per discipline, is one of the things the tool is designed to measure.

## Design

Three layers, deliberately separated so each is usable and testable in isolation:

```
LAYER 3  cli.py       Batch CSV workflows. JSON summary → stdout, logs → stderr.
LAYER 2  core.py      retrieve_pdf() — one typed call, no side effects, no sys.exit.
LAYER 1  sources.py   Seven source adapters + the candidate cascade.
```

**The cascade is the core contribution.** Naïve retrievers ask each source for *a* URL and give up when it fails. OAcquire collects *every* candidate URL from *every* enabled source — all OA locations from Unpaywall, all `link` objects from Crossref, every anchor and `citation_pdf_url` meta-tag on the landing page — deduplicates them, and then attempts each in priority order. Every attempt is validated: magic-byte inspection rejects HTML served with a PDF content-type, and a size floor rejects publisher stub pages. Failures are recorded with a diagnostic code, not silently dropped.

## Sources

Attempted in this order:

| # | Source | Requires | Notes |
|---|---|---|---|
| 1 | **PubMed Central** | — | NCBI OA API; auto-converts PMID/DOI → PMCID |
| 2 | **Europe PMC** | — | EBI REST API; strong biomedical coverage |
| 3 | **Unpaywall** | `--email` | Per their Terms of Service |
| 4 | **OpenAlex** | `--openalex-api-key` | Opt-in via `--openalex` |
| 5 | **Semantic Scholar** | — | Opt-in via `--semantic-scholar`; strong for CS/engineering |
| 6 | **Crossref** | `--email` (optional) | Publisher metadata link objects; ≤3 workers |
| 7 | **Landing page** | — | `citation_pdf_url` meta-tags and anchor heuristics |

## Install

```bash
pip install oacquire
```

Or from source:

```bash
git clone https://github.com/pecesama/oacquire.git
cd oacquire
pip install -e ".[dev]"
```

## Quick start

```bash
oacquire --input examples/literature.csv --email you@university.edu
```

PDFs land in `pdfs/`; the audit log in `download_report.csv`; a machine-readable summary on stdout.

The input CSV uses a minimal, source-agnostic schema compatible with exports from any database or reference manager:

| Column | Required | Notes |
|---|---|---|
| `Title` | Yes | Used as filename fallback |
| `Authors` | Yes | Author list |
| `DOI` | Yes\* | Primary identifier |
| `PMID` | No | Enables PMC / Europe PMC lookup |
| `PMCID` | No | Skips ID conversion |

\* At least one of `DOI`, `PMID`, or `PMCID` per row.

## Agent / programmatic use

`retrieve_pdf()` is the interface OAcquire was built around. It returns a typed `DownloadResult` — no prints to stdout, no `sys.exit`, no exceptions on the expected failure paths.

```python
from oacquire import retrieve_pdf, build_session

session = build_session()   # reuse across calls

result = retrieve_pdf(
    doi="10.3390/sym17122083",
    email="you@university.edu",
    session=session,
)

if result.ok:
    ingest_to_vector_store(result.pdf_path)
elif result.status == "not_found":
    flag_for_manual_screening(result.doi, result.note)
```

| Field | Type | Description |
|---|---|---|
| `ok` | `bool` | `True` if a validated PDF was saved |
| `status` | `str` | `downloaded` · `not_found` · `failed` · `skipped` |
| `source` | `str` | Which source succeeded |
| `pdf_path` | `Path \| None` | Path to the saved file |
| `pdf_url` | `str` | URL used |
| `note` | `str` | Diagnostic code (see below) |

### Agent loop

OAcquire was built for exactly this pattern: an agent resolving a list of
screened works into a full-text corpus, routing each outcome without human
intervention. Because `retrieve_pdf()` never raises on the expected failure
paths and returns a typed result, the loop stays branch-clean.

```python
from oacquire import retrieve_pdf, build_session

session = build_session()   # reuse one session across the whole corpus

# e.g. the output of a systematic-review screening stage, or an
# OpenAlex / arXiv query feeding a RAG pipeline
screened = [
    {"doi": "10.3390/virtualworlds4040056", "title": "Extended Reality in CS Education"},
    {"doi": "10.3390/app15158679",          "title": "ML and Generative AI in Learning Analytics"},
    # ...
]

corpus, unresolved = [], []
for work in screened:
    result = retrieve_pdf(**work, email="you@university.edu", session=session)
    if result.ok:
        corpus.append(result.pdf_path)          # → chunk, embed, index
    elif result.status == "not_found":
        unresolved.append((work["doi"], result.note))   # → PRISMA exclusion log
    else:
        unresolved.append((work["doi"], f"{result.source}:{result.note}"))

print(f"{len(corpus)} full texts acquired; {len(unresolved)} unresolved")
```

The `unresolved` list is not a dead end — it is your PRISMA "reports not
retrieved" count, already itemised with the reason each work failed. That is the
number reviewers ask for and that most pipelines cannot produce.

## The audit log

`download_report.csv` is not a convenience — it is the point. Each row records what was attempted, what succeeded, and *why* a failure occurred:

| `note` value | Meaning |
|---|---|
| `downloaded` | Validated PDF saved |
| `already_exists` | Skipped (`--skip-existing`) |
| `pdf_too_small:{N}_bytes` | Stub / placeholder PDF rejected |
| `not_pdf_magic_bytes:{ct}` | HTML served as PDF — rejected |
| `http_error:403` | Paywall or bot block |
| `all_candidates_failed:{src}:{why}` | Every candidate URL exhausted |

This distinguishes *"no open-access version exists"* from *"an OA version exists but retrieval failed"* — a distinction that matters for honest PRISMA reporting and that, to our knowledge, no comparable tool records.

## CLI reference

```
--input                     CSV input (required)
--outdir                    PDF output directory (default: pdfs)
--report                    Audit log path (default: download_report.csv)
--email                     Required for Unpaywall; enables Crossref polite pool
--openalex                  Enable OpenAlex (requires --openalex-api-key)
--openalex-api-key          Free key at openalex.org
--semantic-scholar          Enable Semantic Scholar
--semantic-scholar-api-key  Optional; raises rate limits
--doi-column / --pmid-column / --pmcid-column / --title-column
                            Override auto-detected column names
--workers                   Parallel threads (default 1; keep ≤3 with Crossref)
--skip-existing             Resume an interrupted run
--max / --delay / --timeout Batch and politeness controls
--no-pmc / --no-europepmc / --no-unpaywall / --no-crossref / --no-landing-page
                            Disable individual sources (used for ablation studies)
--verbose                   Per-record progress to stderr
--version / --citation      Version string / canonical citation
```

## Web interface

For researchers who don't use a command line, the full pipeline is available in the browser at **[oacquire.streamlit.app](https://oacquire.streamlit.app)** — upload a CSV or paste DOIs, toggle sources, watch progress live, and download the PDFs as a ZIP plus the audit log as CSV.

To run it locally:

```bash
pip install -e ".[app]"
streamlit run app/streamlit_app.py
```

## Responsible use

- **No paywall circumvention.** OAcquire locates only legally open versions: OA journals, preprint servers, institutional repositories, and publisher-authorised links. It has no Sci-Hub backend and will not accept one.
- **Polite traffic.** Requests are delayed and rate-limited by default, with exponential backoff. Keep `--workers ≤ 3` when Crossref is enabled.
- **Identify yourself.** `--email` is required by Unpaywall's terms and places you in Crossref's polite pool.

## Citing OAcquire

If OAcquire contributes to work you publish, please cite the **paper**, not the software archive — this keeps citations consolidated in indexed databases:

```bibtex
@article{santanamancilla2026oacquire,
  title   = {OAcquire: A Multi-Source Corpus Acquisition Layer for Agentic Systematic Reviews},
  author  = {Santana-Mancilla, Pedro C.},
  journal = {arXiv preprint},
  year    = {2026}
}
```

For exact reproducibility, additionally cite the version you ran (e.g. *"retrieval performed with OAcquire v2.0.0, DOI 10.5281/zenodo.21367807"*). Run `oacquire --citation` to print the current canonical citation.

## Contributing

Issues and pull requests are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md). New source adapters are especially valuable; the adapter contract is a single function returning `(url, note)` tuples, and `sources.py` documents it.

## AI usage disclosure

Portions of this codebase and its documentation were developed with the assistance of generative AI tools (Anthropic Claude). All architectural decisions, the source-cascade design, the validation strategy, and the evaluation protocol were made by the human author, who reviewed, tested, and validated all AI-assisted output and is solely responsible for its correctness.

## 👨‍💻 Author

Developed by **Pedro C. Santana-Mancilla** — [pedrosantana.mx](https://www.pedrosantana.mx/)  
As part of his own automation and research tools efforts at the [IHCLab Research Group](https://ihclab.ucol.mx/)
School of Telematics, Universidad de Colima.

MIT licensed.
