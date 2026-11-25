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
