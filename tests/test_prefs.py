"""prefs.json is rewritten on every sidebar drag or zoom: it must never be seen half-written."""

import json
import threading


def test_concurrent_saves_never_expose_a_partial_file(mdv, tmp_path, monkeypatch):
    path = tmp_path / "prefs.json"
    monkeypatch.setattr(mdv, "PREFS_PATH", path)
    prefs = {"expanded": [f"root\x1f/some/long/folder/{i}" for i in range(4000)]}
    mdv.save_prefs(prefs)

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
    writers = [threading.Thread(target=lambda: [mdv.save_prefs(prefs) for _ in range(20)])
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
