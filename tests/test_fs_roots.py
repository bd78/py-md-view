"""The computer tree's roots must not touch slow drives on every repaint."""

import sys
from pathlib import Path

import pytest


def test_roots_are_built_once_per_anchor(mdv, tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(mdv, "_windows_drives", lambda: calls.append(1) or [])
    mdv.filesystem_roots.cache_clear()
    first = mdv.filesystem_roots(tmp_path)
    assert mdv.filesystem_roots(tmp_path) is first
    tree = mdv.build_fs_tree(tmp_path, set())
    assert tree[0]["path"] == str(tmp_path)
    assert "open" not in first[0]                  # the shared roots stay untouched
    assert len(calls) <= 1
    mdv.filesystem_roots.cache_clear()


@pytest.mark.skipif(sys.platform != "win32", reason="drive letters are Windows-only")
def test_drives_are_listed_without_touching_them(mdv, monkeypatch):
    monkeypatch.setattr(mdv, "_windows_drives", lambda: ["Q"])
    real_is_dir = Path.is_dir

    def is_dir(self):
        assert str(self).upper() != "Q:\\", "an offline drive was probed"
        return real_is_dir(self)

    monkeypatch.setattr(Path, "is_dir", is_dir)
    mdv.filesystem_roots.cache_clear()
    assert any(r["path"] == "Q:\\" for r in mdv.filesystem_roots(None))
    mdv.filesystem_roots.cache_clear()


@pytest.mark.skipif(sys.platform != "win32", reason="drive letters are Windows-only")
def test_drive_root_anchor_is_not_probed(mdv, monkeypatch, tmp_path):
    monkeypatch.setattr(mdv, "_windows_drives", lambda: ["Q"])
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    real_is_dir = Path.is_dir

    def is_dir(self):
        assert str(self).upper() != "Q:\\", "an offline drive was probed"
        return real_is_dir(self)

    monkeypatch.setattr(Path, "is_dir", is_dir)
    mdv.filesystem_roots.cache_clear()
    roots = mdv.filesystem_roots(Path("Q:\\"))
    assert sum(r["path"] == "Q:\\" for r in roots) == 1      # anchor and drive list dedupe
    mdv.filesystem_roots.cache_clear()
