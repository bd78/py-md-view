"""The file watcher must survive a tab being closed while it polls."""

import os
import shutil
import threading
import time


def test_watcher_survives_closing_the_active_last_tab(mdv, tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    a, b = tmp_path / "a.md", tmp_path / "b.md"
    a.write_text("# a", "utf-8")
    b.write_text("# b", "utf-8")
    viewer = mdv.Viewer([a, b], style="github", zoom=1.0)
    viewer._mtimes[viewer.tabs[0].path] = viewer._safe_mtime(a)

    # Freeze close_tab halfway: the last tab is gone, the index not yet fixed.
    with viewer._nav:
        viewer.active = 1
        viewer.tabs.pop()
        watcher = threading.Thread(target=viewer._watch_loop, daemon=True)
        watcher.start()
        time.sleep(1.0)                 # the watcher polls during the gap
        viewer.active = 0

    os.utime(a, (time.time() + 5, time.time() + 5))   # a change on disk
    time.sleep(2.0)
    viewer._stop.set()
    shutil.rmtree(viewer._tmpdir, ignore_errors=True)
    # Still watching: the change was seen after the gap.
    assert viewer._mtimes[viewer.tabs[0].path] == viewer._safe_mtime(a)
