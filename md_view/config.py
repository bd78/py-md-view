"""File types, constants, platform flags, the per-user data folder, preferences and the style choice."""

from __future__ import annotations

import json
import os
import sys
import threading
from pathlib import Path

APP_NAME = "md-view"

# The md-view.py that started this process; it sets this on import. assets/ is looked up beside it.
LAUNCHER: Path | None = None

# --------------------------------------------------------------------------- #
# Supported file types
# --------------------------------------------------------------------------- #

MARKDOWN_EXTS = {".md", ".markdown", ".mdown", ".mkd", ".mkdn", ".mdtext"}
MERMAID_EXTS = {".mmd", ".mermaid"}
RASTER_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".ico", ".apng", ".avif"}
SVG_EXTS = {".svg", ".svgz"}
CSV_EXTS = {".csv", ".tsv", ".tab"}
TEXT_EXTS = {".txt", ".text", ".log", ".rst", ".json", ".yml", ".yaml", ".toml", ".ini"}

IMAGE_EXTS = RASTER_EXTS | SVG_EXTS
VIEWABLE_EXTS = MARKDOWN_EXTS | MERMAID_EXTS | IMAGE_EXTS | CSV_EXTS | TEXT_EXTS

# Pinned and checked: this script runs in a page that can call into Python.
# To upgrade, change both values (sha256 of dist/mermaid.min.js, as served).
MERMAID_VERSION = "11.17.2"
MERMAID_SHA256 = "581ed7d74bd9048d0e3a91363927d72ef22942d7722546b27f7cc29e35390eb8"
MERMAID_CDN = f"https://cdn.jsdelivr.net/npm/mermaid@{MERMAID_VERSION}/dist/mermaid.min.js"

ZOOM_STEPS = (0.25, 0.33, 0.50, 0.67, 0.75, 0.90, 1.00,
              1.10, 1.25, 1.50, 1.75, 2.00, 2.50, 3.00, 4.00, 5.00)

# Presentation styles. Each one is a full look: palette, syntax colours,
# mermaid theme and type stack.
STYLES = ("light", "dark", "github", "github-ext")
STYLE_LABELS = {"light": "Light", "dark": "Dark", "github": "GitHub",
                "github-ext": "GitHub Ext"}
STYLE_BG = {"light": "#fcfcfd", "dark": "#0d1117", "github": "#ffffff",
            "github-ext": "#ffffff"}
# GitHub's look, with tables allowed to grow past the text column.
DEFAULT_STYLE = "github-ext"
# Pygments styles, in order of preference per look.
STYLE_PYGMENTS = {
    "light": ("friendly", "default"),
    "dark": ("github-dark", "monokai", "native"),
    "github": ("github-light", "default"),
    "github-ext": ("github-light", "default"),
}

# Body typeface. "system" keeps whatever the chosen style specifies.
FONTS = ("system", "sans", "serif", "mono")
FONT_LABELS = {"system": "System", "sans": "Sans", "serif": "Serif", "mono": "Monospace"}

# Rainbow CSV: one colour per column, cycling.
CSV_COLOURS = 10
CSV_MAX_ROWS = 5000


# --------------------------------------------------------------------------- #
# Paths, config, theme
# --------------------------------------------------------------------------- #

def data_dir() -> Path:
    """Per-user directory for cached assets and preferences."""
    if sys.platform == "win32":
        root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support"
    else:
        root = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    d = root / APP_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def assets_dir() -> Path:
    d = data_dir() / "assets"
    d.mkdir(parents=True, exist_ok=True)
    return d


PREFS_PATH = None  # resolved lazily so --help never touches the disk


def load_prefs() -> dict:
    global PREFS_PATH
    PREFS_PATH = data_dir() / "prefs.json"
    try:
        return json.loads(PREFS_PATH.read_text("utf-8"))
    except Exception:
        return {}


_PREFS_LOCK = threading.Lock()


def save_prefs(prefs: dict) -> None:
    """Write via a temp file and a rename, so a crash or a second writer never
    leaves a half-written prefs.json (which would silently reset every setting)."""
    path = PREFS_PATH or data_dir() / "prefs.json"
    tmp = path.with_name(f"prefs.{os.getpid()}.tmp")
    with _PREFS_LOCK:       # bridge calls persist from several threads; cleanup stays inside so it cannot delete another thread's staged file
        try:
            tmp.write_text(json.dumps(prefs, indent=2), "utf-8")
            os.replace(tmp, path)
        except Exception:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
            # preferences are a convenience, never a failure mode


def resolve_style(requested: str | None, prefs: dict) -> str:
    """Pick a style: explicit flag, then the remembered one, then the default.

    A remembered style only counts once it was chosen while DEFAULT_STYLE was
    the default: prefs saved by an older version are moved onto the new
    default once, and any choice made after that sticks.
    """
    if requested in STYLES:
        return requested
    if prefs.get("style_default") == DEFAULT_STYLE:
        for candidate in (prefs.get("style"), prefs.get("theme")):
            if candidate in STYLES:
                return candidate
    return DEFAULT_STYLE


_WIN_HIDDEN_ATTRS = 0x2 | 0x4   # FILE_ATTRIBUTE_HIDDEN | FILE_ATTRIBUTE_SYSTEM
_IS_WINDOWS = sys.platform == "win32"
_IS_MAC = sys.platform == "darwin"
