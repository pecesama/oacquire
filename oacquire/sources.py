"""
LAYER 1 - Source adapters: PMC, Europe PMC, Unpaywall, OpenAlex,
Semantic Scholar, Crossref, and DOI landing-page scanning. Each adapter
returns candidate PDF URLs; the cascade in discover_pdf() aggregates them.

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

from .config import CROSSREF_MAX_WORKERS, PDF_LIKE_RE, DiscoveryConfig, logger
from .http import http_get
from .parsing import (PDFLinkHTMLParser, clean_text, extract_doi, normalize_pmcid,
                     normalize_pmid, safe_filename, unique_preserve_order)

# ---------------------------------------------------------------------------
# LAYER 1 — CORE LIBRARY: source-specific finders
# ---------------------------------------------------------------------------

def find_pmc_pdf(session: requests.Session, pmcid: str, timeout: int) -> Tuple[str, str]:
    if not pmcid:
        return "", "no_pmcid"
    oa_url = f"https://www.ncbi.nlm.nih.gov/pmc/utils/oa/oa.fcgi?id={quote(pmcid)}"
    try:
        resp = http_get(session, oa_url, timeout)
        root = ET.fromstring(resp.text)
    except Exception as exc:
        return "", f"pmc_lookup_error:{exc}"

    if root.find("error") is not None:
        return "", f"pmc_error:{clean_text(root.find('error').text)}"  # type: ignore[union-attr]

    for record in root.findall(".//record"):
        for link in record.findall("link"):
            if clean_text(link.attrib.get("format")).lower() == "pdf":
                href = clean_text(link.attrib.get("href"))
                if href.startswith("ftp://ftp.ncbi.nlm.nih.gov"):
                    href = href.replace("ftp://ftp.ncbi.nlm.nih.gov", "https://ftp.ncbi.nlm.nih.gov", 1)
                return href, "pmc_pdf_found"
    return "", "pmc_pdf_not_found"


def convert_to_pmcid(
    session: requests.Session,
    *,
    pmid: str = "",
    doi: str = "",
    timeout: int,
) -> Tuple[str, str]:
    """Try PMID first, fall back to DOI for PMCID conversion via NCBI ID Converter."""
    identifier = pmid or doi
    if not identifier:
        return "", "idconv_no_identifier"
    api_url = (
        "https://pmc.ncbi.nlm.nih.gov/tools/idconv/api/v1/articles/"
        f"?ids={quote(identifier, safe='')}&format=json"
    )
    try:
        resp = http_get(session, api_url, timeout)
        data = resp.json()
    except Exception as exc:
        return "", f"idconv_error:{exc}"

    for rec in (data.get("records", []) if isinstance(data, dict) else []):
        pmcid = normalize_pmcid(rec.get("pmcid", ""))
        if pmcid:
            return pmcid, "idconv_pmcid_found"
    return "", "idconv_pmcid_not_found"


def find_europepmc_pdf(
    session: requests.Session,
    doi: str,
    pmid: str,
    timeout: int,
) -> Tuple[str, str]:
    """Query the Europe PMC REST API for an open-access PDF link."""
    if doi:
        identifier = f"DOI:{doi}"
    elif pmid:
        identifier = f"EXT_ID:{pmid} AND SRC:MED"
    else:
        return "", "europepmc_no_identifier"

    api_url = (
        "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
        f"?query={quote(identifier)}&resulttype=core&format=json&pageSize=1"
    )
    try:
        resp = http_get(session, api_url, timeout)
        data = resp.json()
    except Exception as exc:
        return "", f"europepmc_lookup_error:{exc}"

    results = (data.get("resultList") or {}).get("result") or []
    if not results:
        return "", "europepmc_no_results"

    article = results[0]
    for entry in (article.get("fullTextUrlList", {}).get("fullTextUrl") or []):
        if isinstance(entry, dict):
            doc_style = (entry.get("documentStyle") or "").lower()
            availability = (entry.get("availability") or "").lower()
            url = clean_text(entry.get("url"))
            if doc_style == "pdf" and url and availability in {"open", ""}:
                return url, "europepmc_pdf_found"

    # Fallback: derive PMCID from response and try PMC directly
    pmcid_val = normalize_pmcid(clean_text(article.get("pmcid")))
    if pmcid_val:
        return find_pmc_pdf(session, pmcid_val, timeout)

    return "", "europepmc_no_pdf_url"


def pick_unpaywall_pdf_url(data: Dict[str, object]) -> List[Tuple[str, str]]:
    """Return all deduped OA PDF candidates from an Unpaywall response."""
    candidates: List[Tuple[str, str]] = []
    best = data.get("best_oa_location") or {}
    if isinstance(best, dict):
        pdf = clean_text(best.get("url_for_pdf"))
        url = clean_text(best.get("url"))
        if pdf:
            candidates.append((pdf, "unpaywall_best_oa_pdf"))
        if url and PDF_LIKE_RE.search(url):
            candidates.append((url, "unpaywall_best_oa_url_pdf"))

    for loc in (data.get("oa_locations") or []):
        if not isinstance(loc, dict):
            continue
        pdf = clean_text(loc.get("url_for_pdf"))
        url = clean_text(loc.get("url"))
        if pdf:
            candidates.append((pdf, "unpaywall_oa_location_pdf"))
        if url and PDF_LIKE_RE.search(url):
            candidates.append((url, "unpaywall_oa_location_url_pdf"))

    return unique_preserve_order(candidates)


def find_unpaywall_pdf(
    session: requests.Session,
    doi: str,
    email: str,
    timeout: int,
) -> List[Tuple[str, str]]:
    """Return all OA PDF candidates from Unpaywall for a given DOI."""
    if not doi:
        return []
    if not email:
        return []
    api_url = f"https://api.unpaywall.org/v2/{quote(doi, safe='')}?email={quote(email)}"
    try:
        resp = http_get(session, api_url, timeout)
        data = resp.json()
    except Exception as exc:
        logger.debug("Unpaywall lookup failed for %s: %s", doi, exc)
        return []
    return pick_unpaywall_pdf_url(data)


def find_openalex_pdf(
    session: requests.Session,
    doi: str,
    pmid: str,
    api_key: str,
    timeout: int,
) -> Tuple[str, str]:
    """
    Query OpenAlex for an open-access PDF URL.

    Docs: https://docs.openalex.org/how-to-use-the-api/authentication
    Note: OpenAlex moved from a polite-pool email scheme to API key
    authentication. An api_key is required for reliable access.
    Free keys available at https://openalex.org/
    """
    if not api_key:
        return "", "openalex_no_api_key"
    if doi:
        work_id = f"https://doi.org/{doi}"
    elif pmid:
        work_id = f"pmid:{pmid}"
    else:
        return "", "openalex_no_identifier"

    params: Dict[str, str] = {
        "select": "id,open_access,best_oa_location,primary_location",
        "api_key": api_key,
    }

    api_url = f"https://api.openalex.org/works/{quote(work_id, safe=':/.')}"
    try:
        resp = http_get(session, api_url, timeout, params=params)
        data = resp.json()
    except Exception as exc:
        return "", f"openalex_lookup_error:{exc}"

    for loc_key in ("best_oa_location", "primary_location"):
        loc = data.get(loc_key) or {}
        if isinstance(loc, dict):
            pdf = clean_text(loc.get("pdf_url"))
            if pdf:
                return pdf, f"openalex_{loc_key}_pdf"

    return "", "openalex_no_pdf_url"


def find_semantic_scholar_pdf(
    session: requests.Session,
    doi: str,
    pmid: str,
    api_key: str,
    timeout: int,
) -> Tuple[str, str]:
    """Query Semantic Scholar for an open-access PDF URL. Docs: https://api.semanticscholar.org"""
    if doi:
        paper_id = f"DOI:{doi}"
    elif pmid:
        paper_id = f"PMID:{pmid}"
    else:
        return "", "s2_no_identifier"

    headers: Dict[str, str] = {}
    if api_key:
        headers["x-api-key"] = api_key

    api_url = f"https://api.semanticscholar.org/graph/v1/paper/{quote(paper_id, safe=':')}"
    try:
        resp = http_get(session, api_url, timeout,
                        params={"fields": "openAccessPdf"}, headers=headers)
        data = resp.json()
    except Exception as exc:
        return "", f"s2_lookup_error:{exc}"

    oa = data.get("openAccessPdf") or {}
    if isinstance(oa, dict):
        url = clean_text(oa.get("url"))
        if url:
            return url, "s2_open_access_pdf"

    return "", "s2_no_pdf_url"


def find_crossref_pdf(
    session: requests.Session,
    doi: str,
    email: str,
    timeout: int,
) -> List[Tuple[str, str]]:
    """Return all PDF link candidates from Crossref metadata for a given DOI."""
    if not doi:
        return []
    api_url = f"https://api.crossref.org/works/{quote(doi, safe='')}"
    params = {"mailto": email} if email else None
    try:
        resp = http_get(session, api_url, timeout, params=params)
        data = resp.json()
    except Exception as exc:
        logger.debug("Crossref lookup failed for %s: %s", doi, exc)
        return []

    message = (data.get("message") or {}) if isinstance(data, dict) else {}
    links = (message.get("link") or []) if isinstance(message, dict) else []
    candidates: List[Tuple[str, str]] = []

    for link in (links if isinstance(links, list) else []):
        if not isinstance(link, dict):
            continue
        url = clean_text(link.get("URL"))
        content_type = clean_text(link.get("content-type")).lower()
        app = clean_text(link.get("intended-application")).lower()
        if not url:
            continue
        if content_type == "application/pdf":
            candidates.append((url, f"crossref_link_pdf:{app or 'unknown'}"))
        elif PDF_LIKE_RE.search(url):
            candidates.append((url, f"crossref_link_pdf_like:{app or 'unknown'}"))

    return unique_preserve_order(candidates)



def get_landing_page_url(
    session: requests.Session,
    doi: str,
    timeout: int,
) -> Tuple[str, str]:
    """Resolve a DOI to its landing page URL, following redirects."""
    if not doi:
        return "", "no_doi"
    url = f"https://doi.org/{quote(doi, safe='/')}"
    try:
        resp = http_get(
            session, url, timeout,
            allow_redirects=True,
            headers={"Accept": "text/html,application/xhtml+xml"},
            stream=False,
        )
    except Exception as exc:
        return "", f"landing_resolve_error:{exc}"
    return str(resp.url), "landing_resolved"


def find_pdf_from_landing_page(
    session: requests.Session,
    landing_url: str,
    timeout: int,
) -> List[Tuple[str, str]]:
    """Return all PDF link candidates found in a DOI landing page."""
    if not landing_url:
        return []
    try:
        resp = http_get(
            session, landing_url, timeout,
            headers={"Accept": "text/html,application/xhtml+xml"},
        )
    except Exception as exc:
        logger.debug("Landing page fetch failed for %s: %s", landing_url, exc)
        return []

    content_type = clean_text(resp.headers.get("Content-Type")).lower()
    if resp.content[:5] == b"%PDF-":
        return [(str(resp.url), "landing_is_pdf")]

    parser = PDFLinkHTMLParser(str(resp.url))
    try:
        parser.feed(resp.text or "")
    except Exception:
        pass

    return unique_preserve_order(parser.candidates)


def _collect_pdf_candidates(
    session: requests.Session,
    *,
    doi: str,
    pmcid: str,
    pmid: str,
    title: str,
    cfg: DiscoveryConfig,
) -> Tuple[str, List[Tuple[str, str, str]]]:
    """
    Query all configured sources and return every candidate PDF URL found.

    Returns (resolved_pmcid, [(url, source, note), ...]) in priority order.
    The caller is responsible for trying each candidate download and stopping
    at the first success — this is the true multi-source cascade.

    The direct DOI fallback is intentionally excluded: doi.org resolves to a
    landing page, not a PDF, so including it generates spurious 'failed'
    results instead of honest 'not_found' ones.
    """
    candidates: List[Tuple[str, str, str]] = []
    resolved_pmcid = pmcid

    # 1. PMC
    if cfg.use_pmc:
        if not resolved_pmcid and (pmid or doi):
            converted, _ = convert_to_pmcid(session, pmid=pmid, doi=doi, timeout=cfg.timeout)
            if converted:
                resolved_pmcid = converted
        if resolved_pmcid:
            url, note = find_pmc_pdf(session, resolved_pmcid, cfg.timeout)
            if url:
                candidates.append((url, "PMC", note))

    # Resolve landing page once — reused by LandingPage source
    landing_url = ""
    if doi and cfg.use_landing_page:
        landing_url, _ = get_landing_page_url(session, doi, cfg.timeout)

    # 2. Europe PMC
    if cfg.use_europepmc and (doi or pmid):
        url, note = find_europepmc_pdf(session, doi, pmid, cfg.timeout)
        if url:
            candidates.append((url, "EuropePMC", note))

    # 3. Unpaywall — may return multiple OA locations
    if cfg.use_unpaywall and doi:
        for url, note in find_unpaywall_pdf(session, doi, cfg.email, cfg.timeout):
            candidates.append((url, "Unpaywall", note))

    # 4. OpenAlex
    if cfg.use_openalex and (doi or pmid):
        url, note = find_openalex_pdf(session, doi, pmid, cfg.openalex_api_key, cfg.timeout)
        if url:
            candidates.append((url, "OpenAlex", note))

    # 5. Semantic Scholar
    if cfg.use_semantic_scholar and (doi or pmid):
        url, note = find_semantic_scholar_pdf(session, doi, pmid, cfg.s2_api_key, cfg.timeout)
        if url:
            candidates.append((url, "SemanticScholar", note))

    # 6. Crossref — may return multiple PDF links in metadata
    if cfg.use_crossref and doi:
        for url, note in find_crossref_pdf(session, doi, cfg.email, cfg.timeout):
            candidates.append((url, "Crossref", note))

    # 7. Landing-page HTML scan — may find multiple PDF anchors
    if cfg.use_landing_page and landing_url:
        for url, note in find_pdf_from_landing_page(session, landing_url, cfg.timeout):
            candidates.append((url, "LandingPage", note))

    return resolved_pmcid, candidates


def discover_pdf(
    session: requests.Session,
    *,
    doi: str,
    pmcid: str,
    pmid: str,
    title: str,
    cfg: DiscoveryConfig,
) -> Tuple[str, str, str, str]:
    """
    Thin wrapper around _collect_pdf_candidates for backward compatibility.
    Returns (pdf_url, source, note, resolved_pmcid) for the first candidate only.
    Use retrieve_pdf() for full cascade with download retry across all candidates.
    """
    resolved_pmcid, candidates = _collect_pdf_candidates(
        session, doi=doi, pmcid=pmcid, pmid=pmid, title=title, cfg=cfg
    )
    if candidates:
        url, source, note = candidates[0]
        return url, source, note, resolved_pmcid
    return "", "", "no_pdf_url_found", resolved_pmcid


def download_file(
    session: requests.Session,
    url: str,
    output_path: Path,
    timeout: int,
    skip_existing: bool,
) -> Tuple[bool, str]:
    if skip_existing and output_path.exists() and output_path.stat().st_size > 0:
        return True, "already_exists"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    # Use a unique temp name so concurrent downloads of different rows that
    # resolve to the same output filename don't clobber each other's .part file.
    tmp_path = output_path.with_name(
        f"{output_path.stem}.{threading.get_ident()}.part"
    )

    try:
        with session.get(url, timeout=timeout, stream=True,
                         allow_redirects=True) as resp:
            resp.raise_for_status()
            first_chunk = next(resp.iter_content(chunk_size=8192), b"")
            content_type = clean_text(resp.headers.get("Content-Type")).lower()

            # Require %PDF- magic bytes regardless of Content-Type.
            # Some servers (e.g. JMIR) return HTML with HTTP 200 and an
            # ambiguous or missing Content-Type — trusting the header alone
            # produces corrupt "downloaded" files that are actually HTML.
            if not first_chunk.startswith(b"%PDF-"):
                return False, f"not_pdf_magic_bytes:{content_type or 'unknown'}"

            with tmp_path.open("wb") as f:
                if first_chunk:
                    f.write(first_chunk)
                for chunk in resp.iter_content(chunk_size=1024 * 128):
                    if chunk:
                        f.write(chunk)

        if tmp_path.exists() and tmp_path.stat().st_size > 0:
            size = tmp_path.stat().st_size
            # Reject PDF stubs — valid articles are never smaller than 20 KB.
            # Some servers (e.g. JMIR) return a file with a valid %PDF- header
            # but near-empty content (~8 KB) that Adobe cannot open.
            if size < 20_000:
                tmp_path.unlink(missing_ok=True)
                return False, f"pdf_too_small:{size}_bytes"
            tmp_path.rename(output_path)
            return True, "downloaded"
        return False, "download_failed_empty"

    except requests.HTTPError as exc:
        return False, f"http_error:{exc}"
    except requests.RequestException as exc:
        return False, f"request_error:{exc}"
    except OSError as exc:
        return False, f"file_error:{exc}"
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
