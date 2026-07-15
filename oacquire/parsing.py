"""
HTML link discovery and identifier/text normalisation utilities.

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

from .config import (DOI_REGEX, META_PDF_NAMES, META_PDF_PROPERTIES, PDF_LIKE_RE, logger)

# ---------------------------------------------------------------------------
# HTML parser for landing-page PDF discovery
# ---------------------------------------------------------------------------
class PDFLinkHTMLParser(HTMLParser):
    MAX_CANDIDATES = 30

    def __init__(self, base_url: str):
        super().__init__()
        self.base_url = base_url
        self.candidates: List[Tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: Sequence[Tuple[str, Optional[str]]]) -> None:
        if len(self.candidates) >= self.MAX_CANDIDATES:
            return
        attr = {k.lower(): (v or "") for k, v in attrs}

        if tag.lower() == "meta":
            name = attr.get("name", "").strip().lower()
            prop = attr.get("property", "").strip().lower()
            content = attr.get("content", "").strip()
            if content:
                if name in META_PDF_NAMES:
                    self.candidates.append((urljoin(self.base_url, content), f"landing_meta:{name}"))
                elif prop in META_PDF_PROPERTIES:
                    self.candidates.append((urljoin(self.base_url, content), f"landing_meta:{prop}"))
                elif PDF_LIKE_RE.search(content):
                    self.candidates.append((urljoin(self.base_url, content), "landing_meta:pdf_like_content"))

        elif tag.lower() == "link":
            rel = attr.get("rel", "").lower()
            href = attr.get("href", "").strip()
            type_ = attr.get("type", "").lower()
            if href:
                absolute = urljoin(self.base_url, href)
                if "alternate" in rel and "application/pdf" in type_:
                    self.candidates.append((absolute, "landing_link:alternate_pdf"))
                elif "application/pdf" in type_ or PDF_LIKE_RE.search(absolute):
                    self.candidates.append((absolute, "landing_link:pdf_like"))

        elif tag.lower() == "a":
            href = attr.get("href", "").strip()
            if href:
                absolute = urljoin(self.base_url, href)
                if PDF_LIKE_RE.search(absolute):
                    self.candidates.append((absolute, "landing_anchor:pdf_like"))


# ---------------------------------------------------------------------------
# Text / identifier utilities
# ---------------------------------------------------------------------------
def clean_text(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"nan", "none"} else text


def safe_filename(text: str, max_len: int = 150) -> str:
    text = re.sub(r"[\\/:*?\"<>|]+", "_", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = text[:max_len].rstrip(" .")
    return text or "article"


def normalize_pmcid(value: str) -> str:
    value = clean_text(value).upper()
    if not value:
        return ""
    value = value.replace("PMCID:", "").replace("PMC", "")
    value = re.sub(r"\D", "", value)
    return f"PMC{value}" if value else ""


def normalize_pmid(value: str) -> str:
    value = clean_text(value)
    if not value:
        return ""
    return re.sub(r"\D", "", value)


def extract_doi(text: str) -> str:
    text = clean_text(text)
    if not text:
        return ""
    for prefix in (
        "https://doi.org/", "http://doi.org/",
        "https://dx.doi.org/", "http://dx.doi.org/",
        "doi:",
    ):
        text = text.replace(prefix, "")
    text = text.strip()
    match = DOI_REGEX.search(text)
    # Return "" when no valid DOI pattern found — avoids sending raw citation
    # text as a fake DOI to every upstream API.
    return match.group(0).rstrip(".);,") if match else ""


def detect_column(fieldnames: List[str], preferred: str, candidates: List[str]) -> str:
    if preferred and preferred in fieldnames:
        return preferred
    lower_map = {name.lower(): name for name in fieldnames}
    for candidate in candidates:
        if candidate.lower() in lower_map:
            return lower_map[candidate.lower()]
    return ""


def iter_rows(csv_path: Path) -> Tuple[List[str], List[Dict[str, str]]]:
    with csv_path.open("r", encoding="utf-8-sig", errors="replace", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        return (reader.fieldnames or [], rows)


def unique_preserve_order(items: Iterable[Tuple[str, str]]) -> List[Tuple[str, str]]:
    out: List[Tuple[str, str]] = []
    seen: set = set()
    for url, note in items:
        if not url or url in seen:
            continue
        seen.add(url)
        out.append((url, note))
    return out


def choose_output_name(doi: str, pmcid: str, pmid: str, title: str, index: int) -> str:
    if doi:
        stem = safe_filename(doi.replace("/", "_"))
    elif pmcid:
        stem = safe_filename(pmcid)
    elif pmid:
        stem = safe_filename(f"PMID_{pmid}")
    elif title:
        stem = safe_filename(title)
    else:
        stem = f"article_{index:04d}"
    return f"{stem}.pdf"
