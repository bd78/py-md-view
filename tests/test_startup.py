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
