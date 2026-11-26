"""Finding, verifying and downloading the pinned mermaid.js."""

from __future__ import annotations

import sys
from pathlib import Path

from . import __version__, config
from .config import APP_NAME, MERMAID_CDN, MERMAID_VERSION


def vendored_mermaid() -> Path | None:
    """A mermaid.min.js shipped next to the md-view.py launcher wins over the cache."""
    if config.LAUNCHER is None:
        return None
    local = config.LAUNCHER.parent / "assets" / "mermaid.min.js"
    return local if local.is_file() and local.stat().st_size > 100_000 else None


def _mermaid_ok(data: bytes) -> bool:
    import hashlib
    return hashlib.sha256(data).hexdigest() == config.MERMAID_SHA256   # tests patch config, so read it there


def cached_mermaid() -> Path | None:
    """The verified download. Named by version, so an older, unchecked cache never counts."""
    p = config.assets_dir() / f"mermaid-{MERMAID_VERSION}.min.js"
    try:
        if p.is_file() and _mermaid_ok(p.read_bytes()):
            return p
    except OSError:
        pass
    # Adopt a cache from before pinning when it is exactly this release, so an
    # offline machine keeps its diagrams.
    legacy = config.assets_dir() / "mermaid.min.js"
    try:
        if legacy.is_file() and _mermaid_ok(legacy.read_bytes()):
            legacy.replace(p)
            return p
    except OSError:
        pass
    return None


def find_mermaid() -> Path | None:
    return vendored_mermaid() or cached_mermaid()


def fetch_mermaid(force: bool = False, timeout: int = 60, quiet: bool = False) -> Path | None:
    """Download mermaid.min.js into the user cache. Returns the path, or None."""
    if not force:
        existing = find_mermaid()
        if existing:
            return existing
    import urllib.error
    import urllib.request

    target = config.assets_dir() / f"mermaid-{MERMAID_VERSION}.min.js"
    tmp = target.with_suffix(".part")
    try:
        if not quiet:
            print(f"Downloading mermaid.js from {MERMAID_CDN} ...", file=sys.stderr)
        req = urllib.request.Request(MERMAID_CDN, headers={"User-Agent": f"{APP_NAME}/{__version__}"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
        if not _mermaid_ok(data):
            raise ValueError(f"checksum mismatch for mermaid {MERMAID_VERSION}")
        tmp.write_bytes(data)
        tmp.replace(target)
        if not quiet:
            print(f"Saved {target} ({len(data) / 1e6:.1f} MB)", file=sys.stderr)
        return target
    except (urllib.error.URLError, OSError, ValueError, TimeoutError) as exc:
        tmp.unlink(missing_ok=True)
        if not quiet:
            print(f"Could not download mermaid.js: {exc}", file=sys.stderr)
        return None
