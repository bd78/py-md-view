"""Turning a link in a document into a path, and handing a path to the operating system."""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path


def _path_from_href(raw: str, base: Path) -> Path | None:
    """Resolve a possibly file://-encoded href into a local path."""
    raw = (raw or "").strip()
    if not raw:
        return None
    raw = raw.split("#", 1)[0]
    if not raw:
        return None
    from urllib.parse import unquote, urlparse
    from urllib.request import url2pathname
    try:
        if raw.lower().startswith("file:"):
            parsed = urlparse(raw)
            local = unquote(parsed.path)
            if sys.platform == "win32" and re.match(r"^/[A-Za-z]:", local):
                local = local[1:]
            if parsed.netloc and sys.platform == "win32":
                local = rf"\\{parsed.netloc}{local}"
            return _resolve_local(Path(local))
        return _resolve_local(base / url2pathname(raw))
    except (OSError, ValueError):
        return None


def _is_network_path(path: Path) -> bool:
    """A Windows path starting with two backslashes: touching it may make this PC sign in to another host.

    That includes the device spellings \\\\.\\UNC\\host\\share and \\\\?\\UNC\\host\\share, which a
    file:// link can produce; a local \\\\?\\C:\\ path through a link is asked about too.
    """
    return sys.platform == "win32" and str(path).startswith("\\\\")


def _resolve_local(path: Path) -> Path:
    return path if _is_network_path(path) else path.resolve()


def _os_open(path: Path) -> None:
    try:
        if sys.platform == "win32":
            os.startfile(str(path))  # noqa: S606
        elif sys.platform == "darwin":
            import subprocess
            subprocess.Popen(["open", str(path)])
        else:
            import subprocess
            subprocess.Popen(["xdg-open", str(path)])
    except OSError as exc:
        print(f"Could not open {path}: {exc}", file=sys.stderr)
