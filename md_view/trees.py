"""The two sidebar trees: directory listings, filesystem roots, and the open-documents tree."""

from __future__ import annotations

import functools
import os
import sys
from pathlib import Path

from . import config
from .config import VIEWABLE_EXTS


TREE_CHILD_LIMIT = 500   # a directory listing this long is already unreadable
TREE_MAX_DEPTH = 24




def _is_hidden(entry: os.DirEntry) -> bool:
    """Skip dot-files and, on Windows, hidden/system entries."""
    if entry.name.startswith("."):
        return True
    if config._IS_WINDOWS:
        try:
            # scandir already fetched the attributes on Windows: no extra syscall.
            return bool(entry.stat(follow_symlinks=False).st_file_attributes
                        & config._WIN_HIDDEN_ATTRS)
        except (OSError, AttributeError):
            return False
    return False


def _scan_dir(path: Path) -> tuple[list[dict], int] | None:
    """One pass over a directory, or None when it cannot be read."""
    try:
        with os.scandir(path) as scan:
            raw = list(scan)
    except (OSError, ValueError):
        return None

    dirs: list[dict] = []
    files: list[dict] = []
    splitext = os.path.splitext
    for entry in raw:
        try:
            if _is_hidden(entry):
                continue
            if entry.is_dir(follow_symlinks=False):
                dirs.append({"name": entry.name, "path": entry.path, "dir": True})
            elif splitext(entry.name)[1].lower() in VIEWABLE_EXTS:
                files.append({"name": entry.name, "path": entry.path, "dir": False})
        except OSError:
            continue

    key = lambda item: item["name"].lower()  # noqa: E731
    dirs.sort(key=key)
    files.sort(key=key)
    merged = dirs + files
    if len(merged) > TREE_CHILD_LIMIT:
        return merged[:TREE_CHILD_LIMIT], len(merged) - TREE_CHILD_LIMIT
    return merged, 0


# Listings keyed by directory path, stamped with the directory's mtime. Every
# navigation rebuilds the sidebar, which re-lists every expanded folder; a
# folder whose mtime has not moved has the same children as last time.
_DIR_CACHE: dict[str, tuple[int, tuple[list[dict], int]]] = {}
_DIR_CACHE_LIMIT = 128


def dir_entries(path: Path) -> tuple[list[dict], int]:
    """Sub-directories and viewable files of `path`, plus a truncation count.

    Only viewable files are listed: this tree exists to find something to open,
    and hiding the rest keeps it short. Callers must treat the result as
    read-only; it may be served from the cache again.
    """
    key = str(path)
    try:
        stamp = os.stat(path).st_mtime_ns
    except OSError:
        stamp = None
    if stamp is not None:
        hit = _DIR_CACHE.get(key)
        if hit is not None and hit[0] == stamp:
            return hit[1]
    result = _scan_dir(path)
    if result is None:
        return [], 0            # unreadable: never cache, it may become readable
    if stamp is not None:
        if len(_DIR_CACHE) >= _DIR_CACHE_LIMIT:
            del _DIR_CACHE[next(iter(_DIR_CACHE))]
        _DIR_CACHE[key] = (stamp, result)
    return result


def documents_anchor(doc_paths: list[Path]) -> Path | None:
    """The deepest folder containing every open document.

    Deliberately derived from all open documents rather than the active one: a
    root that changed identity on every tab switch would move out from under
    whatever the reader had just expanded.
    """
    parents = [str(p.parent) for p in doc_paths if p is not None]
    if not parents:
        return None
    try:
        return Path(os.path.commonpath(parents))
    except ValueError:
        return Path(parents[0])       # spread across drives; anchor on the first


# shortcut: built once per anchor, so a drive plugged in later shows up only
# after a restart; upgrade to a refresh button if that is missed.
@functools.cache
def filesystem_roots(anchor: Path | None = None) -> list[dict]:
    """Starting points for the computer tree. Read-only: the list is shared.

    `anchor` is fixed for the session by the caller. It must not follow the
    documents around: recomputing it would reshape the tree whenever a file was
    opened, discarding whatever the reader had expanded and, if the new anchor
    happened to be an already-expanded folder, dumping all of its children.
    """
    roots: list[dict] = []
    seen: set[str] = set()

    def add(root_id: str, label: str, path: Path | None, *, probe: bool = True) -> None:
        if path is None:
            return
        try:
            if probe and not path.is_dir():
                return
            key = str(path.resolve() if probe else path).lower()
        except OSError:
            return
        if key in seen:
            return
        seen.add(key)
        roots.append({"name": label, "path": str(path), "dir": True,
                      "root": root_id, "key": node_key(root_id, path)})

    if anchor is not None:
        # Not probed: an open document proves it exists, and the anchor may be a drive root.
        add("anchor", f"{anchor.name or anchor} (documents)", anchor, probe=False)
    home = Path.home()
    add("home", "Home", home, probe=False)   # the home folder is assumed to exist
    for folder in ("Desktop", "Documents", "Downloads"):
        add(folder.lower(), folder, home / folder)

    if sys.platform == "win32":
        for letter in _windows_drives():
            # Not probed: a disconnected network drive blocks for the SMB timeout.
            add(f"drive-{letter.lower()}", f"{letter}:\\", Path(f"{letter}:\\"), probe=False)
    else:
        add("root", "/", Path("/"))
    return roots


KEY_SEP = "\x1f"   # unit separator: cannot appear in a path or a root id


def node_key(root_id: str, path: Path | str) -> str:
    """Identity of a row: which root it hangs from, plus its path.

    Scoping by root matters because one folder can be reachable from several
    roots -- a project under both Home and C:\\, say. Keying on the path alone
    made those occurrences share one open/closed state, so expanding a folder in
    one place silently expanded it in the other.
    """
    return f"{root_id}{KEY_SEP}{path}"


def _same_path(a: Path, b: Path) -> bool:
    """Windows paths compare case-insensitively; POSIX ones do not."""
    if sys.platform == "win32":
        return str(a).rstrip("\\/").lower() == str(b).rstrip("\\/").lower()
    return str(a).rstrip("/") == str(b).rstrip("/")


def _is_under(child: Path, parent: Path) -> bool:
    """True when `child` sits inside `parent` (or is `parent`)."""
    if _same_path(child, parent):
        return True
    try:
        return any(_same_path(p, parent) for p in child.parents)
    except (OSError, ValueError):
        return False


def _windows_drives() -> list[str]:
    try:
        import ctypes
        mask = ctypes.windll.kernel32.GetLogicalDrives()
        return [chr(ord("A") + i) for i in range(26) if mask >> i & 1]
    except Exception:
        return [c for c in "CDEFGHIJKLMNOPQRSTUVWXYZ" if Path(f"{c}:\\").is_dir()]


def build_fs_tree(anchor: Path | None, expanded: set[str]) -> list[dict]:
    """Roots plus the children of every expanded directory, rendered eagerly.

    Server-rendering the open branches means the tree is complete the moment
    the page appears; everything deeper is fetched on demand from the bridge.
    `expanded` holds node keys (see node_key), not bare paths.
    """
    def node_for(entry: dict, root_id: str, depth: int) -> dict:
        node = dict(entry)
        node["root"] = root_id
        node["key"] = node.get("key") or node_key(root_id, node["path"])
        if not node.get("dir"):
            return node
        is_open = node["key"] in expanded
        node["open"] = is_open
        if is_open and depth < TREE_MAX_DEPTH:
            children, more = dir_entries(Path(node["path"]))
            node["children"] = [node_for(child, root_id, depth + 1) for child in children]
            if more:
                node["more"] = more
        return node

    return [node_for(root, root["root"], 0) for root in filesystem_roots(anchor)]


def build_doc_tree(tabs: list, active: int, stale: set[Path],
                   collapsed: set[Path] | None = None) -> list[dict]:
    """The open documents, arranged by their own directory structure.

    Only directories that actually contain an open document appear, and chains
    of single sub-directories are folded into one row so the tree stays short.
    Folders the reader collapsed stay collapsed: the page is rebuilt on every
    navigation, so that state has to be applied here rather than left to the DOM.
    """
    entries = [(i, tab.path) for i, tab in enumerate(tabs) if tab.path is not None]
    if not entries:
        return []

    groups: dict[str, list[tuple[int, Path]]] = {}
    for index, path in entries:
        groups.setdefault(path.anchor or "/", []).append((index, path))

    roots: list[dict] = []
    for anchor in sorted(groups):
        items = groups[anchor]
        parents = [str(path.parent) for _, path in items]
        try:
            base = Path(os.path.commonpath(parents))
        except ValueError:
            base = Path(anchor)
        root = {"name": str(base), "path": str(base), "dir": True, "open": True,
                "is_root": True, "children": []}
        for index, path in items:
            try:
                parts = path.relative_to(base).parts
            except ValueError:
                parts = (path.name,)
            cursor = root
            for part in parts[:-1]:
                child = next((c for c in cursor["children"]
                              if c.get("dir") and c["name"] == part), None)
                if child is None:
                    child = {"name": part, "path": str(Path(cursor["path"]) / part),
                             "dir": True, "open": True, "children": []}
                    cursor["children"].append(child)
                cursor = child
            cursor["children"].append({
                "name": path.name, "path": str(path), "dir": False,
                "tab": index, "active": index == active, "stale": path in stale,
            })
        _sort_tree(root)
        _compact_tree(root)
        # After compaction, so the flag keys on the row's final path.
        _apply_collapsed(root, collapsed or set())
        roots.append(root)
    return roots


def _apply_collapsed(node: dict, collapsed: set[Path]) -> None:
    if node.get("dir"):
        try:
            node["open"] = Path(node["path"]) not in collapsed
        except (OSError, ValueError):
            node["open"] = True
    for child in node.get("children") or []:
        _apply_collapsed(child, collapsed)


def _sort_tree(node: dict) -> None:
    children = node.get("children")
    if not children:
        return
    children.sort(key=lambda c: (not c.get("dir"), c["name"].lower()))
    for child in children:
        _sort_tree(child)


def _compact_tree(node: dict) -> None:
    """Fold a directory whose only child is a directory into a single row."""
    children = node.get("children")
    if not children:
        return
    for child in children:
        _compact_tree(child)
    while (len(children) == 1 and children[0].get("dir")
           and not node.get("is_root") and children[0].get("children")):
        only = children[0]
        node["name"] = f"{node['name']}{os.sep}{only['name']}"
        node["path"] = only["path"]
        node["children"] = children = only["children"]
