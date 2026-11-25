"""A missing mermaid.js must not hold the window back while it downloads."""

import time


def test_slow_mermaid_download_does_not_delay_the_window(mdv, tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    doc = tmp_path / "flow.mmd"
    doc.write_text("graph TD; A-->B", "utf-8")

    monkeypatch.setattr(mdv, "find_mermaid", lambda: None)
    monkeypatch.setattr(mdv, "fetch_mermaid", lambda **kw: time.sleep(10))  # a dead network
    monkeypatch.setattr(mdv, "hand_off", lambda paths: False)
    monkeypatch.setattr(mdv, "InstanceServer", lambda viewer: None)
    shown = []

    class Viewer:
        def __init__(self, paths, **kw):
            pass

        def run(self):
            shown.append(time.monotonic())

    monkeypatch.setattr(mdv, "Viewer", Viewer)
    start = time.monotonic()
    assert mdv.main([str(doc)]) == 0
    assert shown and shown[0] - start < 5


def _viewer(mdv, monkeypatch, cached):
    import threading

    v = mdv.Viewer.__new__(mdv.Viewer)
    v._mermaid_lock = threading.Lock()
    v._mermaid_missing = False
    v._mermaid_repainted = False
    v.repaints = 0
    v.refresh = lambda: setattr(v, "repaints", v.repaints + 1)
    state = {"cached": cached}
    monkeypatch.setattr(mdv, "find_mermaid", lambda: "m.js" if state["cached"] else None)
    return v, state


def test_page_that_missed_mermaid_is_repainted_when_the_download_lands(mdv, monkeypatch):
    v, state = _viewer(mdv, monkeypatch, cached=False)
    v.mermaid_missing()
    assert v.repaints == 0
    state["cached"] = True
    v.mermaid_arrived()
    v.mermaid_arrived()
    assert v.repaints == 1


def test_no_repaint_when_the_page_already_has_mermaid(mdv, monkeypatch):
    v, state = _viewer(mdv, monkeypatch, cached=False)
    state["cached"] = True
    v.mermaid_arrived()
    assert v.repaints == 0


def test_page_that_missed_mermaid_after_the_download_is_repainted_once(mdv, monkeypatch):
    v, _ = _viewer(mdv, monkeypatch, cached=True)
    v.mermaid_missing()
    v.mermaid_missing()
    assert v.repaints == 1
