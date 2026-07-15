"""
LAYER 2 - Agent interface: retrieve_pdf(), the single-call entry point
for notebooks, LLM agents, and automated pipelines.

Part of OAcquire — a multi-source corpus acquisition layer for agentic
systematic reviews.

Copyright (c) 2026 Pedro C. Santana-Mancilla. MIT License.
"""

from __future__ import annotations

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

from .config import DEFAULT_TIMEOUT, DiscoveryConfig, DownloadResult, logger
from .http import build_session
from .parsing import (choose_output_name, clean_text, extract_doi,
                     normalize_pmcid, normalize_pmid, safe_filename)
from .sources import (_collect_pdf_candidates, convert_to_pmcid, discover_pdf,
                      download_file)

# ---------------------------------------------------------------------------
# LAYER 2 — AGENT INTERFACE: retrieve_pdf()
# ---------------------------------------------------------------------------

def retrieve_pdf(
    *,
    doi: str = "",
    pmid: str = "",
    pmcid: str = "",
    title: str = "",
    authors: str = "",
    outdir: Path = Path("pdfs"),
    email: str = "",
    s2_api_key: str = "",
    openalex_api_key: str = "",
    skip_existing: bool = True,
    timeout: int = DEFAULT_TIMEOUT,
    use_pmc: bool = True,
    use_europepmc: bool = True,
    use_unpaywall: bool = True,
    use_openalex: bool = False,
    use_semantic_scholar: bool = False,
    use_crossref: bool = True,
    use_landing_page: bool = True,
    session: Optional[requests.Session] = None,
) -> DownloadResult:
    """
    Programmatic entry point for agents, pipelines, and notebooks.

    Does NOT call sys.exit(). Does NOT print to stdout.
    Propagates only standard Python exceptions.

    Implements a true multi-source cascade: all sources are queried first to
    collect candidate URLs, then each is attempted for download in priority
    order until one succeeds. A source returning a URL that cannot be
    downloaded does not end the process — the next candidate is tried.

    Parameters
    ----------
    doi, pmid, pmcid : str
        At least one identifier should be provided. All are optional.
    title : str
        Used as the output filename stem when no identifier is available.
    outdir : Path
        Directory where the PDF will be saved.
    email : str
        Required by Unpaywall; also used for Crossref polite pool.
    openalex_api_key : str
        Required when use_openalex=True. Free key at https://openalex.org/
    s2_api_key : str
        Optional Semantic Scholar key (only relevant when use_semantic_scholar=True).
    skip_existing : bool
        If True, return status="skipped" when the output file already exists.
    timeout : int
        HTTP timeout in seconds per request.
    use_* : bool
        Toggle individual sources on/off.
    session : requests.Session, optional
        Provide a pre-built session to reuse connections across multiple calls
        (recommended for batch usage inside an agent loop).

    Returns
    -------
    DownloadResult
        result.ok        → True if PDF was saved successfully.
        result.status    → "downloaded" | "not_found" | "failed" | "skipped"
        result.pdf_path  → Path to saved file, or None.
        result.source    → Which source produced the successful download.
        result.note      → Diagnostic note for logging/debugging.

    Example
    -------
    >>> from oacquire import retrieve_pdf
    >>> result = retrieve_pdf(doi="10.1186/s12889-019-6761-x", email="you@uni.edu")
    >>> if result.ok:
    ...     print(result.pdf_path)
    """
    doi = extract_doi(doi)
    pmcid_norm = normalize_pmcid(pmcid)
    pmid_norm = normalize_pmid(pmid)

    cfg = DiscoveryConfig(
        email=email,
        s2_api_key=s2_api_key,
        openalex_api_key=openalex_api_key,
        timeout=timeout,
        use_pmc=use_pmc,
        use_europepmc=use_europepmc,
        use_unpaywall=use_unpaywall,
        use_openalex=use_openalex,
        use_semantic_scholar=use_semantic_scholar,
        use_crossref=use_crossref,
        use_landing_page=use_landing_page,
    )

    _session = session or build_session(timeout)

    resolved_pmcid, candidates = _collect_pdf_candidates(
        _session,
        doi=doi,
        pmcid=pmcid_norm,
        pmid=pmid_norm,
        title=title,
        cfg=cfg,
    )

    if not candidates:
        return DownloadResult(
            doi=doi, pmid=pmid_norm, pmcid_original=pmcid_norm,
            pmcid_resolved=resolved_pmcid, title=title, authors=authors,
            status="not_found", source="",
            pdf_path=None, pdf_url="", note="no_pdf_url_found",
        )

    filename = choose_output_name(doi, resolved_pmcid, pmid_norm, title, 0)
    output_path = Path(outdir) / filename

    # True cascade: try each candidate URL until one downloads successfully.
    last_note = ""
    for pdf_url, source, discovery_note in candidates:
        ok, download_note = download_file(_session, pdf_url, output_path, timeout, skip_existing)

        if ok and download_note == "already_exists":
            return DownloadResult(
                doi=doi, pmid=pmid_norm, pmcid_original=pmcid_norm,
                pmcid_resolved=resolved_pmcid, title=title, authors=authors,
                status="skipped", source=source,
                pdf_path=output_path, pdf_url=pdf_url, note=download_note,
            )
        if ok:
            return DownloadResult(
                doi=doi, pmid=pmid_norm, pmcid_original=pmcid_norm,
                pmcid_resolved=resolved_pmcid, title=title, authors=authors,
                status="downloaded", source=source,
                pdf_path=output_path, pdf_url=pdf_url, note=download_note,
            )

        last_note = f"{source}:{download_note}"
        logger.debug("Candidate failed (%s), trying next source.", last_note)

    # All candidates tried and failed
    return DownloadResult(
        doi=doi, pmid=pmid_norm, pmcid_original=pmcid_norm,
        pmcid_resolved=resolved_pmcid, title=title, authors=authors,
        status="failed", source="",
        pdf_path=None, pdf_url="",
        note=f"all_candidates_failed:{last_note}",
    )
