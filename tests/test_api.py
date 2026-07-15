"""Contract tests for the public API surface (LAYER 2)."""
import oacquire


def test_public_api_is_importable():
    for name in ("retrieve_pdf", "build_session", "DownloadResult", "DiscoveryConfig"):
        assert hasattr(oacquire, name)


def test_download_result_ok_property():
    r = oacquire.DownloadResult(status="downloaded")
    assert r.ok is True
    assert oacquire.DownloadResult(status="not_found").ok is False


def test_version_is_semver():
    parts = oacquire.__version__.split(".")
    assert len(parts) == 3 and all(p.isdigit() for p in parts)


def test_citation_string_is_present():
    assert "OAcquire" in oacquire.CITATION
