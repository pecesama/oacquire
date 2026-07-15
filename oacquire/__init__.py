"""
OAcquire — A Multi-Source Corpus Acquisition Layer for Agentic Systematic Reviews.

OAcquire resolves bibliographic identifiers (DOI / PMID / PMCID) to legally
retrievable open-access full texts by cascading across seven independent
sources, validating each candidate, and emitting an auditable retrieval log
suitable for PRISMA-compliant reporting.

Public API
----------
    retrieve_pdf(...)  -> DownloadResult   Single-record acquisition (agent-facing)
    build_session(...) -> requests.Session Reusable HTTP session with retry/backoff
    DownloadResult                         Typed result record
    DiscoveryConfig                        Source toggles and credentials

Example
-------
    >>> from oacquire import retrieve_pdf, build_session
    >>> session = build_session()
    >>> result = retrieve_pdf(doi="10.3390/sym17122083",
    ...                       email="you@university.edu",
    ...                       session=session)
    >>> result.ok, result.source
    (True, 'Unpaywall')

Citation
--------
If you use OAcquire in your research, please cite the accompanying paper.
See CITATION.cff or run `oacquire --citation`.

Copyright (c) 2026 Pedro C. Santana-Mancilla. MIT License.
"""

from .config import (
    DEFAULT_DELAY,
    DEFAULT_TIMEOUT,
    DEFAULT_WORKERS,
    REPORT_FIELDNAMES,
    TOOL_VERSION,
    DiscoveryConfig,
    DownloadResult,
)
from .core import retrieve_pdf
from .http import build_session, http_get
from .sources import discover_pdf, download_file

__version__ = TOOL_VERSION
__author__ = "Pedro C. Santana-Mancilla"
__license__ = "MIT"

CITATION = (
    "Santana-Mancilla, P. C. (2026). OAcquire: A Multi-Source Corpus Acquisition "
    "Layer for Agentic Systematic Reviews. arXiv preprint. "
    "Software archived at Zenodo, DOI: 10.5281/zenodo.21367807"
)

__all__ = [
    "retrieve_pdf",
    "build_session",
    "http_get",
    "discover_pdf",
    "download_file",
    "DownloadResult",
    "DiscoveryConfig",
    "TOOL_VERSION",
    "REPORT_FIELDNAMES",
    "DEFAULT_TIMEOUT",
    "DEFAULT_DELAY",
    "DEFAULT_WORKERS",
    "CITATION",
    "__version__",
]
