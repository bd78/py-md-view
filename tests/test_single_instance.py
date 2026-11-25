"""Launches that start together must end up as tabs in one window."""

import time

import pytest


@pytest.fixture
def data_home(mdv, tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setattr(mdv, "data_dir", lambda: tmp_path)  # macOS ignores both variables
    return tmp_path


def test_only_one_launch_owns_the_window(mdv, data_home):
    first = mdv.instance_lock()
    assert first is not None
    assert mdv.instance_lock() is None       # a second launch must hand off
    first.close()                            # the owner quits ...
    again = mdv.instance_lock()              # ... and the next launch takes over
    assert again is not None
    again.close()


def test_slow_open_still_counts_as_handed_off(mdv, data_home, tmp_path):
    doc = tmp_path / "a.md"
    doc.write_text("# a", "utf-8")

    class SlowViewer:
        def open_tab(self, path):
            time.sleep(1.5)                  # longer than the sender waits

        def _raise(self):
            pass

    server = mdv.InstanceServer(SlowViewer())
    try:
        assert mdv.hand_off([doc], timeout=0.5)
    finally:
        server.close()


def test_one_failing_open_does_not_drop_the_rest(mdv, data_home, tmp_path):
    docs = [tmp_path / n for n in ("a.md", "b.md")]
    for d in docs:
        d.write_text("# x", "utf-8")
    opened = []

    class FlakyViewer:
        def open_tab(self, path):
            if path == docs[0]:
                raise OSError("disk full")
            opened.append(path)

        def _raise(self):
            pass

    server = mdv.InstanceServer(FlakyViewer())
    try:
        assert mdv.hand_off(docs)
        deadline = time.time() + 2
        while not opened and time.time() < deadline:
            time.sleep(0.05)
    finally:
        server.close()
    assert opened == [docs[1]]


def test_launch_stops_retrying_when_every_file_is_gone(mdv, data_home, tmp_path, monkeypatch):
    doc = tmp_path / "a.md"
    doc.write_text("# a", "utf-8")
    owner = mdv.instance_lock()              # someone else owns the window
    assert owner is not None

    def refuse(paths, timeout=2.0):
        doc.unlink()                         # deleted after the startup check
        return False

    monkeypatch.setattr(mdv, "hand_off", refuse)
    monkeypatch.setattr(mdv.time, "sleep", lambda s: None)
    try:
        assert mdv.main([str(doc)]) == 1
    finally:
        owner.close()
