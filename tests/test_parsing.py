"""Unit tests for identifier normalisation and link-discovery utilities.

These tests are deliberately network-free: every source adapter is exercised
against recorded fixtures in test_sources.py, so the full suite runs offline
and deterministically in CI.
"""
import pytest

from oacquire.parsing import (
    PDFLinkHTMLParser,
    choose_output_name,
    clean_text,
    detect_column,
    extract_doi,
    normalize_pmcid,
    normalize_pmid,
    safe_filename,
    unique_preserve_order,
)


@pytest.mark.parametrize("raw,expected", [
    ("10.3390/sym17122083", "10.3390/sym17122083"),
    ("https://doi.org/10.3390/sym17122083", "10.3390/sym17122083"),
    ("doi:10.1145/3025453.3025912", "10.1145/3025453.3025912"),
    ("See 10.1038/s41586-021-03819-2 for details.", "10.1038/s41586-021-03819-2"),
    ("no identifier here", ""),
    ("", ""),
])
def test_extract_doi(raw, expected):
    assert extract_doi(raw) == expected


@pytest.mark.parametrize("raw,expected", [
    ("PMC1234567", "PMC1234567"),
    ("1234567", "PMC1234567"),
    ("pmc1234567", "PMC1234567"),
    ("", ""),
])
def test_normalize_pmcid(raw, expected):
    assert normalize_pmcid(raw) == expected


@pytest.mark.parametrize("raw,expected", [
    ("PMID: 34567890", "34567890"),
    ("34567890", "34567890"),
    ("not-a-pmid", ""),
])
def test_normalize_pmid(raw, expected):
    assert normalize_pmid(raw) == expected


def test_safe_filename_strips_path_separators():
    out = safe_filename("A/B: a *dangerous* title?")
    assert "/" not in out and ":" not in out and "*" not in out


def test_safe_filename_truncates():
    assert len(safe_filename("x" * 500, max_len=50)) <= 50


def test_choose_output_name_prefers_doi():
    assert choose_output_name("10.1/abc", "PMC1", "123", "Title", 0).endswith(".pdf")
    assert "10.1" in choose_output_name("10.1/abc", "", "", "", 0)


def test_choose_output_name_falls_back_to_index():
    assert choose_output_name("", "", "", "", 7) == "article_0007.pdf"


def test_unique_preserve_order_dedupes_by_url():
    items = [("http://a/1.pdf", "s1"), ("http://a/1.pdf", "s2"), ("http://b/2.pdf", "s3")]
    assert unique_preserve_order(items) == [("http://a/1.pdf", "s1"), ("http://b/2.pdf", "s3")]


def test_detect_column_is_case_insensitive():
    assert detect_column(["Title", "doi", "PMID"], "DOI", ["doi"]) == "doi"


def test_clean_text_handles_none():
    assert clean_text(None) == ""


def test_html_parser_finds_citation_pdf_meta_tag():
    html = (
        '<html><head>'
        '<meta name="citation_pdf_url" content="https://pub.org/article.pdf">'
        '</head><body></body></html>'
    )
    parser = PDFLinkHTMLParser(base_url="https://pub.org/article")
    parser.feed(html)
    assert any("article.pdf" in url for url, _ in parser.candidates)


def test_html_parser_resolves_relative_anchors():
    html = '<html><body><a href="/download/1.pdf">PDF</a></body></html>'
    parser = PDFLinkHTMLParser(base_url="https://pub.org/article/1")
    parser.feed(html)
    assert any(url.startswith("https://pub.org/") for url, _ in parser.candidates)
