"""mermaid.js runs with access to the bridge: only the pinned bytes are accepted."""

import base64
import hashlib
import io
import urllib.request

import pytest

GOOD = b"/* mermaid */" * 10_000


@pytest.fixture
def cache(mdv, tmp_path, monkeypatch):
    monkeypatch.setattr(mdv.config, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(mdv.config, "MERMAID_SHA256", hashlib.sha256(GOOD).hexdigest())
    monkeypatch.setattr(mdv.mermaid_assets, "vendored_mermaid", lambda: None)
    return mdv.config.assets_dir()


def serve(monkeypatch, payload):
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **kw: io.BytesIO(payload))


def test_tampered_download_is_rejected(mdv, cache, monkeypatch):
    serve(monkeypatch, GOOD + b"alert(1)")
    assert mdv.mermaid_assets.fetch_mermaid(quiet=True) is None
    assert mdv.mermaid_assets.find_mermaid() is None
    assert not any(cache.iterdir())


def test_pinned_download_is_cached(mdv, cache, monkeypatch):
    serve(monkeypatch, GOOD)
    path = mdv.mermaid_assets.fetch_mermaid(quiet=True)
    assert path is not None and path.read_bytes() == GOOD
    assert mdv.mermaid_assets.find_mermaid() == path


def test_old_unchecked_cache_counts_only_if_it_matches(mdv, cache):
    legacy = cache / "mermaid.min.js"
    legacy.write_bytes(GOOD + b"x")
    assert mdv.mermaid_assets.find_mermaid() is None
    legacy.write_bytes(GOOD)
    assert mdv.mermaid_assets.find_mermaid() is not None


def test_cdn_fallback_carries_the_hash(mdv, cache):
    page = mdv.page.build_page(body="", title="t", mode="mermaid", style="github", zoom=1.0,
                          fit=False, scroll=0.0, base=None, can_go_back=False,
                          with_mermaid=True)
    expected = base64.b64encode(hashlib.sha256(GOOD).digest()).decode()   # the pin the cache fixture patched in
    assert f'integrity="sha256-{expected}"' in page


def test_tampered_versioned_cache_is_a_miss(mdv, cache):
    p = cache / f"mermaid-{mdv.config.MERMAID_VERSION}.min.js"
    p.write_bytes(GOOD)
    assert mdv.mermaid_assets.find_mermaid() == p
    p.write_bytes(GOOD + b"alert(1)")
    assert mdv.mermaid_assets.find_mermaid() is None


def test_vendored_copy_is_found_beside_the_launcher(mdv, tmp_path, monkeypatch):
    # The package lives elsewhere (md_view/, or site-packages), but assets/ sits next to md-view.py.
    assert mdv.config.LAUNCHER.name == "md-view.py"
    monkeypatch.setattr(mdv.config, "LAUNCHER", tmp_path / "md-view.py")
    assert mdv.mermaid_assets.vendored_mermaid() is None
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "mermaid.min.js").write_bytes(b"x" * 100_001)
    assert mdv.mermaid_assets.vendored_mermaid() == tmp_path / "assets" / "mermaid.min.js"
