"""
Configuration constants, logger, and typed data models.

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


# ---------------------------------------------------------------------------
# Logger
# ---------------------------------------------------------------------------
logger = logging.getLogger("oacquire")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
TOOL_VERSION = "2.0.0"
DEFAULT_TIMEOUT = 30
DEFAULT_DELAY = 0.5
DEFAULT_WORKERS = 1

USER_AGENT = (
    f"open-pdf-downloader/{TOOL_VERSION} "
    "(+https://github.com/pecesama/oacquire)"
)

DOI_REGEX = re.compile(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.IGNORECASE)
PDF_LIKE_RE = re.compile(r"(?:\.pdf(?:$|[?#]))|(?:/pdf(?:$|[/?#]))", re.IGNORECASE)

META_PDF_NAMES = {
    "citation_pdf_url",
    "eprints.document_url",
    "wkhealth_pdf_url",
    "pdf_url",
}
META_PDF_PROPERTIES = {
    "og:pdf",
    "og:pdf:url",
}

REPORT_FIELDNAMES = [
    "row_index",
    "title",
    "authors",
    "pmid",
    "doi",
    "pmcid_original",
    "pmcid_resolved",
    "source",
    "status",
    "pdf_url",
    "filename",
    "note",
]

# Names of all boolean source flags in DiscoveryConfig (used for **kwargs passthrough)
_SOURCE_FLAG_NAMES = (
    "use_pmc",
    "use_europepmc",
    "use_unpaywall",
    "use_openalex",
    "use_semantic_scholar",
    "use_crossref",
    "use_landing_page",
)

# Crossref polite pool documented concurrency limit.
# https://api.crossref.org/swagger-ui/index.html (rate limiting section)
CROSSREF_MAX_WORKERS = 3

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

class DiscoveryConfig(NamedTuple):
    email: str = ""
    s2_api_key: str = ""
    openalex_api_key: str = ""
    timeout: int = DEFAULT_TIMEOUT
    use_pmc: bool = True
    use_europepmc: bool = True
    use_unpaywall: bool = True
    # OpenAlex: disabled by default. The polite-pool email parameter is treated
    # as legacy by their current docs; authenticated access uses --openalex-api-key.
    # Enable with --openalex (opt-in). Free key at https://openalex.org/
    use_openalex: bool = False
    use_semantic_scholar: bool = False   # opt-in: enable with --semantic-scholar
    use_crossref: bool = True
    use_landing_page: bool = True


@dataclass
class DownloadResult:
    """
    Returned by retrieve_pdf(). Designed for clean consumption by agents,
    pipelines, and notebooks — no side effects, no sys.exit.
    """
    status: str = "failed"   # "downloaded" | "not_found" | "failed" | "skipped" | "error"
    source: str = ""         # "PMC" | "EuropePMC" | "Unpaywall" | "OpenAlex" | ...
    pdf_path: Optional[Path] = None
    pdf_url: str = ""
    note: str = ""
    doi: str = ""
    pmid: str = ""
    pmcid_original: str = ""
    pmcid_resolved: str = ""
    title: str = ""
    authors: str = ""        # populated when authors column is present in input CSV

    def as_dict(self) -> Dict[str, str]:
        """Serialize to a plain dict (e.g. for JSON / CSV reporting)."""
        d = asdict(self)
        d["pdf_path"] = str(self.pdf_path) if self.pdf_path else ""
        return d

    @property
    def ok(self) -> bool:
        return self.status == "downloaded"
