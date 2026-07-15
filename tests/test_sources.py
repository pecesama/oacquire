"""Source-adapter tests against recorded API fixtures (no network access)."""
import pytest

from oacquire.sources import pick_unpaywall_pdf_url


def test_unpaywall_collects_best_and_all_locations():
    payload = {
        "best_oa_location": {"url_for_pdf": "https://repo.org/best.pdf",
                             "url": "https://repo.org/best"},
        "oa_locations": [
            {"url_for_pdf": "https://repo.org/best.pdf"},          # duplicate
            {"url_for_pdf": "https://mirror.org/alt.pdf"},          # extra candidate
            {"url": "https://landing.org/view"},                    # not PDF-like
        ],
    }
    urls = [u for u, _ in pick_unpaywall_pdf_url(payload)]
    assert urls[0] == "https://repo.org/best.pdf"      # best location wins priority
    assert "https://mirror.org/alt.pdf" in urls        # cascade keeps fallbacks
    assert urls.count("https://repo.org/best.pdf") == 1  # deduped
    assert "https://landing.org/view" not in urls      # non-PDF filtered out


def test_unpaywall_empty_payload_yields_no_candidates():
    assert pick_unpaywall_pdf_url({}) == []


def test_unpaywall_tolerates_null_oa_locations():
    assert pick_unpaywall_pdf_url({"best_oa_location": None, "oa_locations": None}) == []
