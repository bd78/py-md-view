"""mermaid.js runs with access to the bridge: only the pinned bytes are accepted."""

import hashlib
import io
import urllib.request

import pytest

GOOD = b"/* mermaid */" * 10_000


@pytest.fixture
def cache(mdv, tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setattr(mdv, "MERMAID_SHA256", hashlib.sha256(GOOD).hexdigest())
    monkeypatch.setattr(mdv, "vendored_mermaid", lambda: None)
    return mdv.assets_dir()


def serve(monkeypatch, payload):
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **kw: io.BytesIO(payload))


def test_tampered_download_is_rejected(mdv, cache, monkeypatch):
    serve(monkeypatch, GOOD + b"alert(1)")
    assert mdv.fetch_mermaid(quiet=True) is None
    assert mdv.find_mermaid() is None
    assert not any(cache.iterdir())


def test_pinned_download_is_cached(mdv, cache, monkeypatch):
    serve(monkeypatch, GOOD)
    path = mdv.fetch_mermaid(quiet=True)
    assert path is not None and path.read_bytes() == GOOD
    assert mdv.find_mermaid() == path


def test_old_unchecked_cache_counts_only_if_it_matches(mdv, cache):
    legacy = cache / "mermaid.min.js"
    legacy.write_bytes(GOOD + b"x")
    assert mdv.find_mermaid() is None
    legacy.write_bytes(GOOD)
    assert mdv.find_mermaid() is not None


def test_cdn_fallback_carries_the_hash(mdv, cache):
    page = mdv.build_page(body="", title="t", mode="mermaid", style="github", zoom=1.0,
                          fit=False, scroll=0.0, base=None, can_go_back=False,
                          with_mermaid=True)
    assert 'integrity="sha256-' in page
