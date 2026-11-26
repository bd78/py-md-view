"""The computer tree's roots must not touch slow drives on every repaint."""

import sys
from pathlib import Path

import pytest


def test_roots_are_built_once_per_anchor(mdv, tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(mdv.trees, "_windows_drives", lambda: calls.append(1) or [])
    mdv.trees.filesystem_roots.cache_clear()
    first = mdv.trees.filesystem_roots(tmp_path)
    assert mdv.trees.filesystem_roots(tmp_path) is first
    tree = mdv.trees.build_fs_tree(tmp_path, set())
    assert tree[0]["path"] == str(tmp_path)
    assert "open" not in first[0]                  # the shared roots stay untouched
    assert len(calls) == (1 if sys.platform == "win32" else 0)   # once per anchor, and only on Windows
    mdv.trees.filesystem_roots.cache_clear()


@pytest.mark.skipif(sys.platform != "win32", reason="drive letters are Windows-only")
def test_drives_are_listed_without_touching_them(mdv, monkeypatch, tmp_path):
    listed = []
    monkeypatch.setattr(mdv.trees, "_windows_drives", lambda: listed.append(1) or ["Q"])
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))   # Q:\ can only come from the fake
    real_is_dir = Path.is_dir

    def is_dir(self):
        assert str(self).upper() != "Q:\\", "an offline drive was probed"
        return real_is_dir(self)

    monkeypatch.setattr(Path, "is_dir", is_dir)
    mdv.trees.filesystem_roots.cache_clear()
    roots = mdv.trees.filesystem_roots(None)
    assert any(r["path"] == "Q:\\" for r in roots)
    assert listed
    assert any(r["root"] == "home" and r["path"] == str(tmp_path) for r in roots)   # the home patch is in effect
    mdv.trees.filesystem_roots.cache_clear()


@pytest.mark.skipif(sys.platform != "win32", reason="drive letters are Windows-only")
def test_drive_root_anchor_is_not_probed(mdv, monkeypatch, tmp_path):
    listed = []
    monkeypatch.setattr(mdv.trees, "_windows_drives", lambda: listed.append(1) or ["Q"])
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    real_is_dir = Path.is_dir

    def is_dir(self):
        assert str(self).upper() != "Q:\\", "an offline drive was probed"
        return real_is_dir(self)

    monkeypatch.setattr(Path, "is_dir", is_dir)
    mdv.trees.filesystem_roots.cache_clear()
    roots = mdv.trees.filesystem_roots(Path("Q:\\"))
    assert listed                                                 # the drive list really supplied Q:
    assert sum(r["path"] == "Q:\\" for r in roots) == 1      # anchor and drive list dedupe
    mdv.trees.filesystem_roots.cache_clear()
