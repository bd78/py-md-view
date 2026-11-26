"""prefs.json is rewritten on every sidebar drag or zoom: it must never be seen half-written."""

import json
import threading


def test_concurrent_saves_never_expose_a_partial_file(mdv, tmp_path, monkeypatch):
    path = tmp_path / "prefs.json"
    monkeypatch.setattr(mdv.config, "PREFS_PATH", path)
    prefs = {"expanded": [f"root\x1f/some/long/folder/{i}" for i in range(4000)]}
    mdv.config.save_prefs(prefs)

    broken, stop = [], threading.Event()

    def read():
        while not stop.is_set():
            try:
                json.loads(path.read_text("utf-8"))
            except ValueError:
                broken.append(1)
            except OSError:
                pass        # mid-rename on Windows; a real reader just retries

    reader = threading.Thread(target=read)
    reader.start()
    writers = [threading.Thread(target=lambda: [mdv.config.save_prefs(prefs) for _ in range(20)])
               for _ in range(4)]
    for w in writers:
        w.start()
    for w in writers:
        w.join()
    stop.set()
    reader.join()

    assert not broken
    assert json.loads(path.read_text("utf-8")) == prefs
    assert [p.name for p in tmp_path.iterdir()] == ["prefs.json"]


def test_failed_save_cleans_up_while_holding_the_lock(mdv, tmp_path, monkeypatch):
    """Cleanup outside the lock could delete a temp file another thread just staged."""
    monkeypatch.setattr(mdv.config, "PREFS_PATH", tmp_path / "prefs.json")
    monkeypatch.setattr(mdv.os, "replace", lambda *a: (_ for _ in ()).throw(OSError("boom")))
    held = []
    real_unlink = type(tmp_path).unlink
    monkeypatch.setattr(type(tmp_path), "unlink",
                        lambda self, *a, **k: (held.append(mdv.config._PREFS_LOCK.locked()),
                                               real_unlink(self, *a, **k))[1])
    mdv.config.save_prefs({"a": 1})
    assert held == [True]
    assert list(tmp_path.iterdir()) == []
