"""A document must not be able to run script: the page can call into Python."""

import re
from pathlib import Path


def test_only_md_view_scripts_carry_the_nonce(mdv):
    body = '<p>hi</p><script>evil()</script><img src=x onerror="evil()">'
    page = mdv.build_page(body=body, title="t", mode="doc", style="github",
                          zoom=1.0, fit=False, scroll=0.0, base=None,
                          can_go_back=False, with_mermaid=True)
    csp = re.search(r'Content-Security-Policy" content="([^"]+)"', page).group(1)
    script_src = re.search(r"script-src ([^;]+);", csp).group(1)
    nonce = re.fullmatch(r"'nonce-([\w-]+)'", script_src).group(1)

    assert "'unsafe-inline'" not in script_src
    # config, viewer, mermaid loader and its ready call -- and nothing else
    assert page.count(f'nonce="{nonce}"') == 4
    assert "<script>evil()</script>" in page          # present, but blocked by CSP


def test_welcome_and_error_pages_have_no_inline_handlers(mdv):
    for page in (mdv.render_welcome("github"), mdv.render_error("x", "y", "github")):
        assert "onclick=" not in page
        assert 'id="pickFile"' in page


def test_tree_never_hands_files_to_the_os(mdv, tmp_path, monkeypatch):
    exe = tmp_path / "setup.exe"
    exe.write_bytes(b"MZ")
    monkeypatch.setattr(mdv, "_os_open", lambda p: (_ for _ in ()).throw(AssertionError(p)))

    class FakeViewer:
        def open_tab(self, path):
            raise AssertionError(path)

    assert mdv.Viewer.open_from_tree(FakeViewer(), str(exe)) is False
