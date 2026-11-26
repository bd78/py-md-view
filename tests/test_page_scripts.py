"""A document must not be able to run script: the page can call into Python."""

import json
import re
import sys
from pathlib import Path, PurePosixPath
from types import SimpleNamespace
from urllib.parse import urlsplit
from urllib.request import url2pathname

import pytest


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


def test_a_document_form_cannot_navigate_the_window(mdv):
    page = mdv.build_page(body='<form action="https://evil.example"><button>x</button></form>',
                          title="t", mode="doc", style="github", zoom=1.0, fit=False,
                          scroll=0.0, base=None, can_go_back=False, with_mermaid=False)
    csp = re.search(r'Content-Security-Policy" content="([^"]+)"', page).group(1)
    assert "form-action 'none'" in csp


def test_welcome_and_error_pages_have_no_inline_handlers(mdv):
    for page in (mdv.render_welcome("github"), mdv.render_error("x", "y", "github")):
        assert "onclick=" not in page
        assert 'id="pickFile"' in page


def test_markdown_disables_raw_meta_pragmas(mdv, tmp_path):
    doc = tmp_path / "sample.md"
    doc.write_text(
        '<META content="15" HTTP-EQUIV=refresh>\n\n'
        '<div>\n<meta/http-equiv="Refresh" content="15" />\n</div>\n\n'
        '<details><summary>Details</summary>Text</details>\n\n'
        '`<meta http-equiv=refresh content=15>`\n',
        encoding="utf-8",
    )
    page = mdv.render_document(doc, style="github", zoom=1.0, fit=False,
                               scroll=0.0, can_go_back=False)
    assert '<meta http-equiv="" content="15" HTTP-EQUIV=refresh>' in page
    assert '<meta http-equiv=""/http-equiv="Refresh" content="15" />' in page
    assert '<details><summary>Details</summary>Text</details>' in page
    assert '<code>&lt;meta http-equiv=refresh content=15&gt;</code>' in page
    assert '<meta http-equiv="Content-Security-Policy"' in page


def test_only_current_generated_page_can_call_viewer_actions(mdv, monkeypatch):
    class Window:
        def expose(self, *functions):
            self.exposed = {fn.__name__: fn for fn in functions}

    def create_window(title, *, url, **kwargs):
        assert kwargs.get("js_api") is None
        window.url = url
        return window

    def start(on_start, **kwargs):
        assert set(window.exposed) == {"dispatch"}
        dispatch = window.exposed["dispatch"]
        staged = urlsplit(window.url)
        key = staged.fragment
        staged_path = Path(url2pathname(staged.path))
        page = staged_path.read_text("utf-8")
        assert key and key not in page
        for bad_key in ("", "wrong", "é", None):
            assert dispatch(bad_key, "set_find_query", ["denied"]) is None
        assert viewer.find_query == ""
        assert dispatch(key, "_persist", []) is None
        assert dispatch(key, "set_find_query", ["allowed"]) is True
        assert viewer.find_query == "allowed"
        new_key = urlsplit(viewer._stage(page)).fragment
        assert new_key != key
        assert dispatch(key, "set_find_query", ["stale"]) is None
        assert viewer.find_query == "allowed"
        assert dispatch(new_key, "set_find_query", ["repainted"]) is True
        assert viewer.find_query == "repainted"

    window = Window()
    monkeypatch.setitem(sys.modules, "webview", SimpleNamespace(
        create_window=create_window, start=start,
    ))
    monkeypatch.setattr(mdv, "load_prefs", dict)
    monkeypatch.setattr(mdv, "save_prefs", lambda prefs: None)
    monkeypatch.setattr(mdv, "_drop_stale_bridge_replies", lambda: None)
    viewer = mdv.Viewer(style="github", zoom=1.0, watch=False)
    monkeypatch.setattr(viewer, "_sidebar", dict)
    viewer.run()


def test_tree_never_hands_files_to_the_os(mdv, tmp_path, monkeypatch):
    exe = tmp_path / "setup.exe"
    exe.write_bytes(b"MZ")
    monkeypatch.setattr(mdv, "_os_open", lambda p: (_ for _ in ()).throw(AssertionError(p)))

    class FakeViewer:
        def open_tab(self, path):
            raise AssertionError(path)

    assert mdv.Viewer.open_from_tree(FakeViewer(), str(exe)) is False


@pytest.mark.skipif(sys.platform != "win32", reason="network shares are Windows paths here")
@pytest.mark.parametrize("href", ["file://zeus/share/a.md", "file://./UNC/zeus/share/a.md"])
def test_network_share_link_asks_before_any_access(mdv, monkeypatch, href):
    asked, shown, touched = [], [], []

    class Window:
        answer = False

        def create_confirmation_dialog(self, title, message):
            asked.append(message)
            return Window.answer

    viewer = SimpleNamespace(current=None, _window=Window(), show=shown.append)
    # resolve() and is_dir() on a share make this PC sign in to that host.
    monkeypatch.setattr(mdv.Path, "resolve", lambda self, *a, **k: touched.append(self) or self)
    monkeypatch.setattr(mdv.Path, "is_dir", lambda self, *a, **k: touched.append(self) or False)

    assert mdv.Viewer.open_path(viewer, href) is False
    assert asked and "zeus" in asked[0]
    assert not touched and not shown                    # declined: nothing was reached

    Window.answer = True
    assert mdv.Viewer.open_path(viewer, href) is True
    assert len(shown) == 1


@pytest.mark.parametrize("name", ["Evil.app", "Evil.APP"])
def test_macos_app_bundle_is_asked_about_not_opened(mdv, tmp_path, monkeypatch, name):
    app = tmp_path / name
    app.mkdir()
    opened, asked = [], []
    monkeypatch.setattr(mdv, "_os_open", opened.append)

    class Window:
        def create_confirmation_dialog(self, title, message):
            asked.append(message)
            return False                        # the reader says no

    viewer = SimpleNamespace(current=None, _window=Window())

    monkeypatch.setattr(mdv, "_IS_MAC", True)   # `open Evil.app` would launch it
    assert mdv.Viewer.open_path(viewer, app.as_uri()) is False
    assert asked and not opened

    monkeypatch.setattr(mdv, "_IS_MAC", False)  # elsewhere a folder just opens
    mdv.Viewer.open_path(viewer, app.as_uri())
    assert opened == [app.resolve()]


def test_document_path_cannot_close_the_config_script(mdv):
    # Legal on macOS and Linux: a folder named "<" holding one named "script><meta ...>".
    hostile = "/home/me/</script><meta http-equiv=refresh content=0;url=x>&/notes.md"
    tabs = [SimpleNamespace(path=PurePosixPath(hostile))]     # same on a Windows test run
    sidebar = {"docs": mdv.build_doc_tree(tabs, active=0, stale=set())}
    page = mdv.build_page(body="<p>x</p>", title="notes.md", mode="doc", style="github",
                          zoom=1.0, fit=False, scroll=0.0, base=None, can_go_back=False,
                          with_mermaid=False, sidebar=sidebar, find_query="</script>")

    assert "</script><meta" not in page
    # The HTML parser ends a script at the first "</script"; the config must reach it whole.
    start = page.index("window.__MDV__ = ") + len("window.__MDV__ = ")
    config = json.loads(page[start:page.index("</script", start)].rstrip(";"))
    assert config["findQuery"] == "</script>"
    assert hostile in json.dumps(config["docsTree"], ensure_ascii=False)   # value intact
    assert "\\u003c/script\\u003e" in page[start:]


def test_hash_links_never_fall_through_to_the_browser(mdv):
    # <base> makes a bare "#x" (even one written as &#35;x) point at the folder,
    # so the click handler must cancel it and scroll in page itself.
    handler = mdv.VIEWER_JS.split('addEventListener("click", function (e) {\n    var a = e.target.closest', 1)[1]
    handler = handler.split("});", 1)[0]
    assert handler.index("e.preventDefault()") < handler.index('charAt(0) === "#"')
