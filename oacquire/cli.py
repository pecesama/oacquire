"""
LAYER 3 - Command-line entry point for batch CSV workflows.

Part of OAcquire — a multi-source corpus acquisition layer for agentic
systematic reviews.

Copyright (c) 2026 Pedro C. Santana-Mancilla. MIT License.
"""

from __future__ import annotations

import argparse
import os

import csv
import json
import logging
import re
import sys
import threading
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Dict, Iterable, List, NamedTuple, Optional, Sequence, Tuple
from urllib.parse import quote, urljoin, urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .config import (CROSSREF_MAX_WORKERS, DEFAULT_DELAY, DEFAULT_TIMEOUT, DEFAULT_WORKERS,
                     REPORT_FIELDNAMES, TOOL_VERSION, DiscoveryConfig, DownloadResult,
                     _SOURCE_FLAG_NAMES, logger)
from .http import build_session
from .parsing import clean_text, detect_column, iter_rows
from .core import retrieve_pdf

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _print_citation() -> int:
    from . import CITATION
    print(CITATION)
    return 0


def parse_args(argv=None) -> argparse.Namespace:
    if argv is None:
        argv = sys.argv[1:]
    if "--citation" in argv:
        raise SystemExit(_print_citation())
    parser = argparse.ArgumentParser(
        description=(
            "Download open-access PDFs from a CSV using PMC, Europe PMC, "
            "Unpaywall, OpenAlex, Semantic Scholar, Crossref, "
            "and landing-page heuristics."
        )
    )
    # I/O
    parser.add_argument("--version", action="version",
                        version=f"OAcquire {TOOL_VERSION}")
    parser.add_argument("--citation", action="store_true",
                        help="Print the canonical citation for OAcquire and exit.")
    parser.add_argument("--input", required=True, help="Path to CSV input.")
    parser.add_argument("--outdir", default="pdfs", help="Directory where PDFs are saved (default: pdfs).")
    parser.add_argument("--report", default="download_report.csv", help="Output CSV report path.")

    # Column overrides
    parser.add_argument("--doi-column", default="", help="Override DOI column name.")
    parser.add_argument("--pmcid-column", default="", help="Override PMCID column name.")
    parser.add_argument("--pmid-column", default="", help="Override PMID column name.")
    parser.add_argument("--citation-column", default="Citation", help="Citation column used as DOI fallback (default: Citation).")
    parser.add_argument("--title-column", default="Title", help="Title column for filenames/logs (default: Title).")
    parser.add_argument("--authors-column", default="Authors", help="Authors column (default: Authors).")

    # Credentials
    parser.add_argument("--email", default=os.environ.get("UNPAYWALL_EMAIL", ""),
                        help="Email for polite API usage (Unpaywall, Crossref).")
    parser.add_argument("--openalex-api-key", default=os.environ.get("OPENALEX_API_KEY", ""),
                        help="OpenAlex API key (free at https://openalex.org/). Required when --openalex is enabled.")
    parser.add_argument("--semantic-scholar-api-key", default=os.environ.get("S2_API_KEY", ""),
                        help="Semantic Scholar API key (optional; raises rate limits).")

    # Behaviour
    parser.add_argument("--max", type=int, default=0, help="Process only first N rows (0 = all).")
    parser.add_argument("--delay", type=float, default=DEFAULT_DELAY,
                        help=f"Delay between records in seconds (default: {DEFAULT_DELAY}).")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT,
                        help=f"HTTP timeout in seconds (default: {DEFAULT_TIMEOUT}).")
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS,
                        help=f"Parallel download workers (default: {DEFAULT_WORKERS}). "
                             f"Max {CROSSREF_MAX_WORKERS} recommended when Crossref is enabled (their polite pool limit).")

    parser.add_argument("--skip-existing", action="store_true",
                        help="Skip when target PDF already exists.")

    # Source toggles
    parser.add_argument("--no-pmc", action="store_true", help="Disable PMC.")
    parser.add_argument("--no-europepmc", action="store_true", help="Disable Europe PMC.")
    parser.add_argument("--no-unpaywall", action="store_true", help="Disable Unpaywall.")
    parser.add_argument("--openalex", action="store_true",
                        help="Enable OpenAlex (disabled by default). Requires --openalex-api-key.")
    parser.add_argument("--semantic-scholar", action="store_true",
                        help="Enable Semantic Scholar (disabled by default). Useful for CS/engineering literature.")
    parser.add_argument("--no-crossref", action="store_true", help="Disable Crossref.")
    parser.add_argument("--no-landing-page", action="store_true", help="Disable landing-page scan.")

    parser.add_argument("--verbose", action="store_true", help="Print per-record progress to stderr.")
    return parser.parse_args()


# ---------------------------------------------------------------------------
# LAYER 3 — CLI ENTRY POINT
# ---------------------------------------------------------------------------

def _process_row_cli(
    idx: int,
    row: Dict[str, str],
    *,
    doi_col: str,
    pmcid_col: str,
    pmid_col: str,
    citation_col: str,
    title_col: str,
    authors_col: str,
    outdir: Path,
    session: requests.Session,
    cfg: DiscoveryConfig,
    skip_existing: bool,
    total: int,
) -> Dict[str, str]:
    """Extract identifiers from a CSV row and call retrieve_pdf()."""
    title = clean_text(row.get(title_col, "")) if title_col else ""
    authors = clean_text(row.get(authors_col, "")) if authors_col else ""
    doi_raw = row.get(doi_col, "") if doi_col else ""
    if not doi_raw and citation_col:
        doi_raw = row.get(citation_col, "")

    result = retrieve_pdf(
        doi=doi_raw,
        pmid=row.get(pmid_col, "") if pmid_col else "",
        pmcid=row.get(pmcid_col, "") if pmcid_col else "",
        title=title,
        authors=authors,
        outdir=outdir,
        email=cfg.email,
        s2_api_key=cfg.s2_api_key,
        openalex_api_key=cfg.openalex_api_key,
        skip_existing=skip_existing,
        timeout=cfg.timeout,
        use_pmc=cfg.use_pmc,
        use_europepmc=cfg.use_europepmc,
        use_unpaywall=cfg.use_unpaywall,
        use_openalex=cfg.use_openalex,
        use_semantic_scholar=cfg.use_semantic_scholar,
        use_crossref=cfg.use_crossref,
        use_landing_page=cfg.use_landing_page,
        session=session,
    )

    label = result.doi or result.pmcid_resolved or result.pmid or f"row {idx}"
    logger.debug("[%d/%d] %s -> %s via %s (%s)", idx, total, label, result.status, result.source or "none", result.note)

    return {
        "row_index": str(idx),
        "title": result.title,
        "authors": result.authors,
        "pmid": result.pmid,
        "doi": result.doi,
        "pmcid_original": result.pmcid_original,
        "pmcid_resolved": result.pmcid_resolved,
        "source": result.source,
        "status": result.status,
        "pdf_url": result.pdf_url,
        "filename": result.pdf_path.name if result.pdf_path else "",
        "note": result.note,
    }


def main() -> int:
    args = parse_args()

    # Logs → stderr; JSON summary → stdout (agent-friendly separation)
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        stream=sys.stderr,
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    csv_path = Path(args.input)
    outdir = Path(args.outdir)
    report_path = Path(args.report)

    if not csv_path.exists():
        logger.error("Input file not found: %s", csv_path)
        return 2

    fieldnames, rows = iter_rows(csv_path)
    if not rows:
        logger.error("CSV is empty or has no data rows.")
        return 2

    doi_col = detect_column(fieldnames, args.doi_column, ["DOI", "doi"])
    pmcid_col = detect_column(fieldnames, args.pmcid_column, ["PMCID", "pmcid", "pmc id", "PMC ID"])
    pmid_col = detect_column(fieldnames, args.pmid_column, ["PMID", "pmid", "pubmed id", "PubMed ID"])
    citation_col = args.citation_column if args.citation_column in fieldnames else ""
    title_col = args.title_column if args.title_column in fieldnames else ""
    authors_col = args.authors_column if args.authors_column in fieldnames else ""

    # Fix: citation_col is a valid identifier source — don't abort if it's present.
    if not doi_col and not pmcid_col and not pmid_col and not citation_col:
        logger.error(
            "Could not detect DOI, PMCID, PMID, or Citation columns. "
            "Use --doi-column / --pmcid-column / --pmid-column / --citation-column to specify them."
        )
        return 2

    if args.max and args.max > 0:
        rows = rows[: args.max]
        logger.info("Limiting to first %d rows.", args.max)

    workers = max(1, args.workers)

    cfg = DiscoveryConfig(
        email=args.email,
        s2_api_key=args.semantic_scholar_api_key,
        openalex_api_key=args.openalex_api_key,
        timeout=args.timeout,
        use_pmc=not args.no_pmc,
        use_europepmc=not args.no_europepmc,
        use_unpaywall=not args.no_unpaywall,
        use_openalex=args.openalex,
        use_semantic_scholar=args.semantic_scholar,
        use_crossref=not args.no_crossref,
        use_landing_page=not args.no_landing_page,
    )

    # Fail-fast: --openalex is a no-op without an API key — make it explicit.
    if cfg.use_openalex and not cfg.openalex_api_key:
        logger.error(
            "--openalex requires --openalex-api-key. "
            "Get a free key at https://openalex.org/"
        )
        return 2

    # Crossref polite pool is documented to allow max 3 concurrent connections.
    # Warn if the user exceeds this; we don't hard-cap to preserve user autonomy.
    if cfg.use_crossref and workers > CROSSREF_MAX_WORKERS:
        logger.warning(
            "Crossref polite pool recommends max %d concurrent connections. "
            "You requested --workers %d. Consider --no-crossref or reducing workers "
            "to avoid HTTP 429 errors from Crossref.",
            CROSSREF_MAX_WORKERS, workers,
        )

    total = len(rows)
    logger.info("Starting: %d records, %d worker(s).", total, workers)

    report_rows: List[Dict[str, str]] = [{}] * total
    success_count = failed_count = not_found_count = skipped_count = error_count = 0

    # Fix: use thread-local sessions so each worker thread has its own connection
    # pool. requests.Session is not guaranteed thread-safe when shared across threads.
    _thread_local = threading.local()

    def get_thread_session() -> requests.Session:
        if not hasattr(_thread_local, "session"):
            _thread_local.session = build_session(cfg.timeout)
        return _thread_local.session

    def process_row_with_local_session(idx: int, row: Dict[str, str]) -> Dict[str, str]:
        return _process_row_cli(
            idx, row,
            doi_col=doi_col, pmcid_col=pmcid_col, pmid_col=pmid_col,
            citation_col=citation_col, title_col=title_col, authors_col=authors_col,
            outdir=outdir, session=get_thread_session(), cfg=cfg,
            skip_existing=args.skip_existing, total=total,
        )

    if workers == 1:
        session = build_session(args.timeout)
        for idx, row in enumerate(rows, start=1):
            report_rows[idx - 1] = _process_row_cli(
                idx, row,
                doi_col=doi_col, pmcid_col=pmcid_col, pmid_col=pmid_col,
                citation_col=citation_col, title_col=title_col, authors_col=authors_col,
                outdir=outdir, session=session, cfg=cfg,
                skip_existing=args.skip_existing, total=total,
            )
            if args.delay > 0 and idx < total:
                time.sleep(args.delay)
    else:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            # Submit jobs one at a time with delay between submissions so
            # --delay actually throttles outgoing traffic, not result collection.
            futures: Dict = {}
            for idx, row in enumerate(rows, start=1):
                future = executor.submit(process_row_with_local_session, idx, row)
                futures[future] = idx
                if args.delay > 0 and idx < total:
                    time.sleep(args.delay)

            for future in as_completed(futures):
                idx = futures[future]
                try:
                    report_rows[idx - 1] = future.result()
                except Exception as exc:
                    logger.error("Row %d raised an unexpected error: %s", idx, exc)
                    report_rows[idx - 1] = {
                        "row_index": str(idx), "status": "error", "note": str(exc),
                        **{k: "" for k in REPORT_FIELDNAMES if k not in ("row_index", "status", "note")},
                    }

    # Fix: count "error" separately — don't fold it into not_found.
    for r in report_rows:
        s = r.get("status", "")
        if s == "downloaded":
            success_count += 1
        elif s == "failed":
            failed_count += 1
        elif s == "skipped":
            skipped_count += 1
        elif s == "error":
            error_count += 1
        else:
            not_found_count += 1

    report_path.parent.mkdir(parents=True, exist_ok=True)
    with report_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=REPORT_FIELDNAMES, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(report_rows)

    logger.info(
        "Done. downloaded=%d skipped=%d failed=%d not_found=%d errors=%d",
        success_count, skipped_count, failed_count, not_found_count, error_count,
    )

    # stdout carries only the machine-readable JSON summary
    summary = {
        "tool_version": TOOL_VERSION,
        "input": str(csv_path),
        "rows_processed": total,
        "downloads_ok": success_count,
        "downloads_skipped": skipped_count,
        "downloads_failed": failed_count,
        "not_found": not_found_count,
        "errors": error_count,
        "outdir": str(outdir),
        "report": str(report_path),
        "columns": {
            k: v for k, v in {
                "doi": doi_col,
                "pmid": pmid_col,
                "pmcid": pmcid_col,
                "doi_fallback_column": citation_col,
            }.items() if v
        },
        "sources_enabled": {
            "pmc": cfg.use_pmc,
            "europepmc": cfg.use_europepmc,
            "unpaywall": cfg.use_unpaywall,
            "openalex": cfg.use_openalex,
            "semantic_scholar": cfg.use_semantic_scholar,
            "crossref": cfg.use_crossref,
            "landing_page": cfg.use_landing_page,
        },
        "workers": workers,
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
