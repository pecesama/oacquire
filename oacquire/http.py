"""
HTTP session construction with retry/backoff, and polite GET helpers.

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

from .config import DEFAULT_TIMEOUT, USER_AGENT, logger

# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------
def build_session(timeout: int = DEFAULT_TIMEOUT) -> requests.Session:
    """Return a requests.Session with retry logic and shared headers."""
    retry_strategy = Retry(
        total=3,
        connect=0,        # Don't retry DNS failures or SSL errors — they won't resolve
        read=1,           # Retry once on read timeouts (transient)
        backoff_factor=1.0,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "HEAD"],
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session = requests.Session()
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update({
        "User-Agent": USER_AGENT,
        "Accept": "application/pdf, application/json, text/xml, text/html, */*",
    })
    return session


def http_get(
    session: requests.Session,
    url: str,
    timeout: int,
    **kwargs,
) -> requests.Response:
    response = session.get(url, timeout=timeout, **kwargs)
    response.raise_for_status()
    return response
