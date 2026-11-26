#!/usr/bin/env python3
"""md-view - a lightweight native viewer for Markdown, Mermaid, images and SVG.

Read-only by design: no editing, no autosave, nothing that can touch your files.

Usage:
    md-view.py DOCUMENT.md
    md-view.py sketch.mmd
    md-view.py diagram.svg
    md-view.py --register          # associate .md / .mmd with this viewer (Windows)
    md-view.py --fetch-assets      # pre-download mermaid.js for offline use

Author: bd78 (https://github.com/bd78)
"""

from __future__ import annotations

import argparse
import errno
import functools
import html
import json
import os
import re
import socket
import sys
import threading
import time
from pathlib import Path

# urllib.request, secrets, shutil, tempfile and webbrowser are imported where
# they are used: together they cost ~45 ms at start-up, and the common
# "hand the file to the running window" launch needs none of them.


# The md_view package sits next to this launcher (in the repo, or in site-packages after `pip install .`).
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from md_view import __version__, config, links, markdown_render, mermaid_assets, styles, viewer_js  # noqa: E402

config.LAUNCHER = Path(__file__).resolve()   # the package looks beside it for assets/
from md_view.config import (  # noqa: E402
    APP_NAME, CSV_COLOURS, CSV_EXTS, CSV_MAX_ROWS, DEFAULT_STYLE, FONT_LABELS, FONTS, IMAGE_EXTS,
    MARKDOWN_EXTS, MERMAID_CDN, MERMAID_EXTS, RASTER_EXTS, STYLE_BG,
    STYLE_LABELS, STYLES, SVG_EXTS, VIEWABLE_EXTS, ZOOM_STEPS,
)

# --------------------------------------------------------------------------- #
# HTML assembly
# --------------------------------------------------------------------------- #

ICONS = {
    "back": '<svg viewBox="0 0 24 24"><path d="M15 18l-6-6 6-6"/></svg>',
    "minus": '<svg viewBox="0 0 24 24"><path d="M5 12h14"/></svg>',
    "plus": '<svg viewBox="0 0 24 24"><path d="M12 5v14M5 12h14"/></svg>',
    "fit": '<svg viewBox="0 0 24 24"><path d="M4 9V5a1 1 0 011-1h4M20 9V5a1 1 0 00-1-1h-4'
           'M4 15v4a1 1 0 001 1h4M20 15v4a1 1 0 01-1 1h-4"/></svg>',
    "style": '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/>'
             '<path d="M12 3a9 9 0 000 18z" fill="currentColor" stroke="none"/></svg>',
    "reload": '<svg viewBox="0 0 24 24"><path d="M21 12a9 9 0 11-2.6-6.4M21 3v5h-5"/></svg>',
    "open": '<svg viewBox="0 0 24 24"><path d="M3 7a2 2 0 012-2h4l2 2h7a2 2 0 012 2v8a2 2 0 01-2 2H5a2 2 0 01-2-2z"/></svg>',
    "panel": '<svg viewBox="0 0 24 24"><rect x="3" y="4" width="18" height="16" rx="2"/>'
             '<path d="M9 4v16"/></svg>',
    "font": '<svg viewBox="0 0 24 24"><path d="M4 19l6-14 6 14M6.5 14h7M16 19h4"/></svg>',
    "find": '<svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="7"/>'
            '<path d="M20.5 20.5L16.5 16.5"/></svg>',
    "up": '<svg viewBox="0 0 24 24"><path d="M6 15l6-6 6 6"/></svg>',
    "down": '<svg viewBox="0 0 24 24"><path d="M6 9l6 6 6-6"/></svg>',
    "align": '<svg viewBox="0 0 24 24"><path d="M4 6h6M4 12h6M4 18h6'
             'M14 6h6M14 12h6M14 18h6"/></svg>',
}


def choice_menu_html(menu_id: str, kind: str, heading: str, options: list[tuple[str, str]],
                     active: str, *, swatches: bool = False,
                     keys: bool = True) -> str:
    """A radio-style popup menu. `options` is a list of (value, label)."""
    items = []
    for index, (value, label) in enumerate(options, start=1):
        checked = "true" if value == active else "false"
        swatch = f'<span class="swatch s-{value}"></span>' if swatches else '<span></span>'
        hint = f'<span class="key">{index}</span>' if keys else "<span></span>"
        items.append(
            f'    <button type="button" role="menuitemradio" data-value="{value}" '
            f'aria-checked="{checked}">{swatch}'
            f'<span>{html.escape(label)}</span>{hint}'
            f'<span class="tick"></span></button>'
        )
    rows = "\n".join(items)
    return (f'<div class="menu" id="{menu_id}" data-kind="{kind}" role="menu" '
            f'aria-label="{html.escape(heading)}" hidden>\n'
            f'    <div class="group">{html.escape(heading)}</div>\n{rows}\n  </div>')


def sidebar_html() -> str:
    """The shell. Both trees are painted by the viewer script from __MDV__."""
    return """<div id="sidebar">
  <section class="pane docs" id="paneDocs">
    <header data-pane="docs"><span class="caret">&#9662;</span>
      <span>Open documents</span><span class="count" id="docsCount"></span></header>
    <div class="tree" id="docsTree"></div>
  </section>
  <div id="paneGrip" title="Drag to resize the panels"></div>
  <section class="pane files" id="paneFiles">
    <header data-pane="files"><span class="caret">&#9662;</span>
      <span>Computer</span>
      <button class="reveal" id="revealBtn" type="button"
              title="Reveal the open document">&#9678;</button></header>
    <div class="tree" id="filesTree"></div>
  </section>
</div>
<div id="sideResize" title="Drag to resize"></div>"""


def find_bar_html() -> str:
    """Search UI for the open document. Hidden until asked for."""
    return f"""<div id="findbar" role="search" hidden>
  <input id="findInput" type="text" placeholder="Find in document"
         spellcheck="false" autocomplete="off" aria-label="Find in document">
  <span id="findCount" aria-live="polite"></span>
  <button id="findPrev" type="button" title="Previous match (Shift+Enter)"
          disabled>{ICONS["up"]}</button>
  <button id="findNext" type="button" title="Next match (Enter)"
          disabled>{ICONS["down"]}</button>
  <div class="sep"></div>
  <button id="findClose" type="button" title="Close (Esc)">&times;</button>
</div>"""


def tabs_html(tabs: list[dict], active: int) -> str:
    """The tab strip. `tabs` is a list of {"title", "path", "stale"} dicts."""
    cells = []
    for index, tab in enumerate(tabs):
        selected = "true" if index == active else "false"
        title = tab.get("title") or "Untitled"
        cells.append(
            f'  <div class="tab" role="tab" data-index="{index}" '
            f'aria-selected="{selected}" data-stale="{1 if tab.get("stale") else 0}" '
            f'title="{html.escape(tab.get("path") or title, quote=True)}">'
            f'<span class="dot"></span>'
            f'<span class="label">{html.escape(title)}</span>'
            f'<button class="x" type="button" data-close="{index}" '
            f'title="Close tab (Ctrl+W)">&times;</button></div>'
        )
    strip = "\n".join(cells)
    return (
        f'<div id="tabs" role="tablist" aria-label="Open documents">\n{strip}\n'
        f'  <button id="newTab" type="button" title="Open a file in a new tab '
        f'(Ctrl+T)">+</button>\n</div>'
    )


def toolbar_html(title: str, subtitle: str, can_go_back: bool, mode: str, style: str,
                 font: str = "system", csv_align: bool = False) -> str:
    back_disabled = "" if can_go_back else " disabled"
    fit_btn = ""
    if mode in ("image", "mermaid"):
        fit_btn = (
            f'<button class="tb" id="fitBtn" title="Fit to window (F)">{ICONS["fit"]}</button>'
        )
    align_btn = (
        f'<button class="tb" id="alignBtn" aria-pressed="{"true" if csv_align else "false"}" '
        f'title="Align columns">{ICONS["align"]}</button>'
    )
    dims = '<span id="dims" class="dims"></span>' if mode == "image" else ""
    label = html.escape(title)
    sub = f' <span style="color:var(--fg-faint)">{html.escape(subtitle)}</span>' if subtitle else ""
    return f"""<div id="bar">
  <button class="tb" id="sidebarBtn" title="Toggle sidebar (Ctrl+B)">{ICONS["panel"]}</button>
  <button class="tb" id="backBtn" title="Back ([)"{back_disabled}>{ICONS["back"]}</button>
  <button class="tb" id="openBtn" title="Open file (Ctrl+O)">{ICONS["open"]}</button>
  <button class="tb" id="reloadBtn" title="Rebuild this tab from disk (F5)">{ICONS["reload"]}</button>
  <button class="tb" id="findBtn" title="Find in document (Ctrl+F)">{ICONS["find"]}</button>
  <div class="sep"></div>
  <div class="title" dir="ltr"><b>{label}</b>{sub} {dims}</div>
  <div class="sep"></div>
  <button class="tb" id="zoomOut" title="Zoom out (Ctrl+-)">{ICONS["minus"]}</button>
  <div id="zoomLabel">100%</div>
  <button class="tb" id="zoomIn" title="Zoom in (Ctrl++)">{ICONS["plus"]}</button>
  {fit_btn}
  {align_btn}
  <div class="sep"></div>
  <div class="menu-wrap">
    <button class="tb" data-menu="fontMenu" id="fontBtn" title="Font"
            aria-haspopup="menu" aria-expanded="false">{ICONS["font"]}</button>
    {choice_menu_html("fontMenu", "font", "Font",
                      [(f, FONT_LABELS[f]) for f in FONTS], font, keys=False)}
  </div>
  <div class="menu-wrap">
    <button class="tb" data-menu="styleMenu" id="styleBtn" title="Style (Ctrl+D cycles)"
            aria-haspopup="menu" aria-expanded="false">{ICONS["style"]}</button>
    {choice_menu_html("styleMenu", "style", "Style",
                      [(s, STYLE_LABELS[s]) for s in STYLES], style, swatches=True)}
  </div>
</div>"""


def build_page(*, body: str, title: str, subtitle: str = "", mode: str,
               style: str, zoom: float, fit: bool, scroll: float,
               base: Path | None, can_go_back: bool,
               with_mermaid: bool, vector: bool = False,
               view_box: tuple[float, float] | None = None,
               tabs: list[dict] | None = None, active_tab: int = 0,
               sidebar: dict | None = None, font: str = "system",
               csv: bool = False, csv_align: bool = False,
               find_query: str = "") -> str:
    """Assemble a complete, self-contained HTML page for the webview."""
    if style not in STYLES:
        style = STYLES[0]
    if font not in FONTS:
        font = FONTS[0]
    tabs = tabs or []
    single = len(tabs) <= 1
    sidebar = sidebar or {}
    hidden = not sidebar.get("visible", True)
    width = int(sidebar.get("width") or 264)
    docs_h = int(sidebar.get("docs_height") or 220)
    cfg = {
        "mode": mode, "zoom": zoom, "fit": fit, "scroll": scroll,
        "steps": list(ZOOM_STEPS), "vector": vector,
        "viewBox": list(view_box) if view_box else None,
        "styles": list(STYLES), "fonts": list(FONTS),
        "csv": csv, "csvAlign": csv_align, "findQuery": find_query,
        "tabCount": len(tabs), "activeTab": active_tab,
        "docsTree": sidebar.get("docs") or [],
        "filesTree": sidebar.get("files") or [],
        "panes": sidebar.get("panes") or {},
        "sidebarWidth": width, "docsHeight": docs_h,
    }
    # The config sits inside <script>: a path or search text holding
    # "</script>" would end it early. JSON-escaped, JS still reads < > &.
    # Built here: f-string expressions may not contain "\" before Python 3.12.
    cfg_json = (json.dumps(cfg).replace("<", "\\u003c").replace(">", "\\u003e")
                .replace("&", "\\u0026"))
    base_tag = f'<base href="{html.escape(base.as_uri() + "/", quote=True)}">' if base else ""
    # Only scripts carrying this page's nonce run. A document's own <script>
    # or onerror= would otherwise reach window.pywebview.api.
    import secrets
    nonce = secrets.token_urlsafe(16)

    mermaid_tag = ""
    if with_mermaid:
        path = mermaid_assets.find_mermaid()
        integrity = ""
        if path:
            src = path.as_uri()
        else:
            src = MERMAID_CDN  # last resort; works only if the machine is online
            import base64
            digest = base64.b64encode(bytes.fromhex(config.MERMAID_SHA256)).decode()
            integrity = f' integrity="sha256-{digest}" crossorigin="anonymous"'
        # The second script runs once the first has loaded or failed.
        mermaid_tag = (
            f'<script nonce="{nonce}" src="{html.escape(src, quote=True)}"{integrity}></script>'
            f'<script nonce="{nonce}">__mdv_mermaidReady()</script>'
        )

    return f"""<!doctype html>
<html lang="en" data-style="{style}" data-font="{font}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'self' file: data: blob: https:; script-src 'nonce-{nonce}'; style-src 'unsafe-inline' file:; img-src file: data: blob: https:; object-src 'none'; frame-src 'none'; form-action 'none';">
<title>{html.escape(title)} - {APP_NAME}</title>
{base_tag}
<style>{styles.BASE_CSS}
{styles.pygments_css()}
</style>
</head>
<body class="mode-{mode}{' single-tab' if single else ''}{' no-sidebar' if hidden else ''}{' is-csv' if csv else ''}"
      style="--sidebar-w: {width}px; --docs-h: {docs_h}px">
{toolbar_html(title, subtitle, can_go_back, mode, style, font, csv_align)}
{sidebar_html()}
{tabs_html(tabs, active_tab)}
{find_bar_html()}
<div id="scroller"><div id="content">{body}</div></div>
<div id="toast"></div>
<script nonce="{nonce}">window.__MDV__ = {cfg_json};</script>
<script nonce="{nonce}">{viewer_js.VIEWER_JS}</script>
{mermaid_tag}
</body>
</html>
"""


# --------------------------------------------------------------------------- #
# Per-document rendering
# --------------------------------------------------------------------------- #

def classify(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in MARKDOWN_EXTS:
        return "markdown"
    if ext in MERMAID_EXTS:
        return "mermaid"
    if ext in SVG_EXTS:
        return "svg"
    if ext in RASTER_EXTS:
        return "raster"
    if ext in CSV_EXTS:
        return "csv"
    return "text"


# --------------------------------------------------------------------------- #
# Delimited text: rainbow columns
# --------------------------------------------------------------------------- #

def sniff_delimiter(sample: str, ext: str) -> str:
    """Best guess at the field separator."""
    if ext in {".tsv", ".tab"}:
        return "\t"
    try:
        import csv as csv_mod
        return csv_mod.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except Exception:
        # Sniffer gives up on short or irregular files; count candidates instead.
        first = sample.split("\n", 1)[0]
        counts = {d: first.count(d) for d in (",", ";", "\t", "|")}
        best = max(counts, key=counts.get)
        return best if counts[best] else ","


def parse_delimited(text: str, ext: str) -> tuple[list[list[str]], str, bool]:
    """Rows, the delimiter used, and whether the file was truncated."""
    import csv as csv_mod
    import io

    delimiter = sniff_delimiter(text[:8192], ext)
    rows: list[list[str]] = []
    truncated = False
    try:
        reader = csv_mod.reader(io.StringIO(text, newline=""), delimiter=delimiter)
        for row in reader:
            if len(rows) >= CSV_MAX_ROWS:
                truncated = True
                break
            rows.append(row)
    except (csv_mod.Error, ValueError):
        # Malformed quoting: fall back to a plain split so something still shows.
        lines = text.splitlines()
        rows = [line.split(delimiter) for line in lines[:CSV_MAX_ROWS]]
        truncated = len(lines) > CSV_MAX_ROWS
    return rows, delimiter, truncated


def render_delimited(rows: list[list[str]], delimiter: str, *,
                     aligned: bool, truncated: bool) -> str:
    """Colour every column, optionally padding fields so columns line up.

    Kept as monospaced text rather than a table: that keeps the file's own shape
    visible, and makes alignment something the reader can turn on and off.
    """
    if not rows:
        return '<div class="csv-info">Empty file.</div>'

    columns = max(map(len, rows))
    widths = [0] * columns
    if aligned:
        for row in rows:
            for index, field in enumerate(row):
                if len(field) > widths[index]:
                    widths[index] = len(field)

    shown = html.escape("\\t" if delimiter == "\t" else delimiter)
    info = (f'<div class="csv-info">{len(rows):,} rows &times; {columns} columns'
            f' &middot; delimiter <code>{shown}</code>'
            f'{" &middot; aligned" if aligned else ""}</div>')

    sep = f'<span class="csv-d">{html.escape(delimiter)}</span>'
    # This runs once per field on files up to CSV_MAX_ROWS long, so the
    # per-cell work is kept to an escape and a couple of concatenations.
    opens = [f'<span class="c{index % CSV_COLOURS}">' for index in range(columns)]
    escape = html.escape
    last = columns - 1
    lines = []
    for number, row in enumerate(rows):
        if aligned:
            cells = [
                opens[index] + escape(field)
                + ("&nbsp;" * (widths[index] - len(field)) if index < last else "")
                + "</span>"
                for index, field in enumerate(row)
            ]
        else:
            cells = [opens[index] + escape(field) + "</span>"
                     for index, field in enumerate(row)]
        klass = "csv-row csv-head" if number == 0 else "csv-row"
        lines.append(f'<div class="{klass}">{sep.join(cells)}</div>')

    note = ""
    if truncated:
        note = (f'<div class="csv-info csv-cut">Showing the first '
                f'{CSV_MAX_ROWS:,} rows.</div>')
    return f'{info}<pre class="csv">{"".join(lines)}</pre>{note}'


# shortcut: one fixed cap; the page, not the read, is what breaks on a huge file.
# Make it a preference if people hit it.
MAX_TEXT_BYTES = 5 * 1024 * 1024


def read_text(path: Path) -> str:
    import codecs

    with path.open("rb") as f:
        data = f.read(MAX_TEXT_BYTES + 1)
    cut = len(data) > MAX_TEXT_BYTES
    data = data[:MAX_TEXT_BYTES]

    def decode(encoding: str, errors: str = "strict") -> str:
        if not cut:
            return data.decode(encoding, errors)    # a lone b"\xef" must still fall to cp1252
        # final=False holds back a character the cut split in two, instead of
        # failing the whole prefix and falling through to another encoding.
        return codecs.getincrementaldecoder(encoding)(errors).decode(data, final=False)

    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        # UTF-16 with a BOM: what Windows PowerShell 5 writes for "cmd > out.txt".
        return decode("utf-16", "replace")
    for encoding in ("utf-8-sig", "cp1252"):   # utf-8-sig also reads BOM-less UTF-8
        try:
            return decode(encoding)
        except UnicodeDecodeError:
            continue
    return decode("latin-1")                    # never fails: every byte is a character


def human_size(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB"):
        if size < 1024:
            return f"{size:.0f} {unit}"
        size /= 1024.0
    return f"{size:.0f} GB"


SVG_TAG = re.compile(r"<svg\b[^>]*>", re.IGNORECASE | re.DOTALL)
SVG_VIEWBOX = re.compile(
    r"viewBox\s*=\s*[\"']\s*[-\d.eE]+[ ,]+[-\d.eE]+[ ,]+"
    r"(?P<w>[-\d.eE]+)[ ,]+(?P<h>[-\d.eE]+)",
    re.IGNORECASE,
)
SVG_ABSOLUTE_LEN = re.compile(r"^\s*[-\d.eE]+\s*(px|pt|pc|cm|mm|in|Q)?\s*$", re.IGNORECASE)


def svg_dimensions(path: Path) -> tuple[float, float] | None:
    """Intrinsic size for an SVG, or None to trust what the engine reports.

    An SVG that declares only a viewBox has no intrinsic size, so the engine
    substitutes a placeholder (a 300x150 box shrunk to the viewBox aspect).
    Zooming from that placeholder makes "100%" meaningless, so in that case the
    viewBox extent is the honest natural size. When width/height *are* given in
    absolute units, the author stated a size and the engine already has it right.
    """
    try:
        head = path.read_bytes()[:16384].decode("utf-8", errors="replace")
    except OSError:
        return None
    tag = SVG_TAG.search(head)
    if not tag:
        return None
    attrs = tag.group(0)

    def sized(name: str) -> bool:
        m = re.search(rf'\b{name}\s*=\s*(["\'])(?P<v>.*?)\1', attrs, re.IGNORECASE | re.DOTALL)
        return bool(m and SVG_ABSOLUTE_LEN.match(m.group("v")))

    if sized("width") and sized("height"):
        return None

    m = SVG_VIEWBOX.search(attrs)
    if not m:
        return None
    try:
        w, h = float(m.group("w")), float(m.group("h"))
        return (w, h) if w > 0 and h > 0 else None
    except ValueError:
        return None


# --------------------------------------------------------------------------- #
# Sidebar trees
# --------------------------------------------------------------------------- #

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


# Parsed documents, keyed by (path, mtime, csv_align). Switching tabs should
# not re-parse markdown or re-run pygments; only a real change or an explicit
# refresh should.
_DOC_CACHE: dict[tuple[str, float | None, bool], dict] = {}
_DOC_CACHE_LIMIT = 32


def invalidate_document(path: Path) -> None:
    """Drop cached output for a file, so the next render re-reads from disk."""
    key = str(path)
    for cached in [k for k in _DOC_CACHE if k[0] == key]:
        _DOC_CACHE.pop(cached, None)


def document_parts(path: Path, *, csv_align: bool = False) -> dict:
    """Parse a document into the pieces build_page needs, with caching."""
    if not path.is_absolute():
        # file:// URLs for the base tag and for <img src> need a full path.
        path = path.resolve()
    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = None
    # csv_align changes the body, so it belongs in the key.
    key = (str(path), mtime, csv_align)
    cached = _DOC_CACHE.get(key)
    if cached is not None:
        return cached
    parts = _parse_document(path, csv_align=csv_align)
    while len(_DOC_CACHE) >= _DOC_CACHE_LIMIT:
        del _DOC_CACHE[next(iter(_DOC_CACHE))]     # oldest first
    _DOC_CACHE[key] = parts
    return parts


def _cut_note(path: Path) -> str:
    """Says so when read_text showed only the start of the file."""
    try:
        size = path.stat().st_size
    except OSError:
        return ""
    return f"first {human_size(MAX_TEXT_BYTES)} of {human_size(size)}" if size > MAX_TEXT_BYTES else ""


def _parse_document(path: Path, *, csv_align: bool = False) -> dict:
    """The expensive half of rendering: read the file and produce a body."""
    kind = classify(path)

    if kind == "markdown":
        # Relative src/href resolve through the page's <base>, set to path.parent.
        body = markdown_render.render_markdown(read_text(path))[0]
        return {"body": body, "mode": "doc", "subtitle": _cut_note(path), "base": path.parent,
                "with_mermaid": 'class="mermaid"' in body, "vector": False, "view_box": None}

    if kind == "mermaid":
        return {"body": markdown_render.mermaid_block(read_text(path)), "mode": "mermaid", "subtitle": _cut_note(path),
                "base": path.parent, "with_mermaid": True, "vector": False, "view_box": None}

    if kind in ("svg", "raster"):
        vector = kind == "svg"
        checker = (" checker" if path.suffix.lower()
                   in {".png", ".gif", ".webp", ".svg", ".ico", ".apng", ".avif"} else "")
        body = (
            f'<img id="imgview" class="imgview{checker}" '
            f'src="{html.escape(path.as_uri(), quote=True)}" alt="{html.escape(path.name)}">'
        )
        try:
            subtitle = human_size(path.stat().st_size)
        except OSError:
            subtitle = ""
        return {"body": body, "mode": "image", "subtitle": subtitle, "base": None,
                "with_mermaid": False, "vector": vector,
                "view_box": svg_dimensions(path) if vector else None}

    if kind == "csv":
        rows, delimiter, truncated = parse_delimited(read_text(path), path.suffix.lower())
        body = render_delimited(rows, delimiter, aligned=csv_align, truncated=truncated)
        columns = max((len(r) for r in rows), default=0)
        return {"body": body, "mode": "doc", "base": path.parent,
                "subtitle": " · ".join(filter(None, (f"{len(rows):,} × {columns}", _cut_note(path)))),
                "with_mermaid": False, "vector": False, "view_box": None, "csv": True}

    # plain text / unknown: show it verbatim rather than guessing
    return {"body": f"<pre><code>{html.escape(read_text(path))}</code></pre>",
            "mode": "doc", "subtitle": _cut_note(path), "base": path.parent,
            "with_mermaid": False, "vector": False, "view_box": None}


def render_document(path: Path, *, style: str, zoom: float, fit: bool,
                    scroll: float, can_go_back: bool,
                    tabs: list[dict] | None = None, active_tab: int = 0,
                    sidebar: dict | None = None, font: str = "system",
                    csv_align: bool = False, find_query: str = "") -> str:
    parts = document_parts(path, csv_align=csv_align)
    return build_page(
        body=parts["body"], title=path.name, subtitle=parts["subtitle"],
        mode=parts["mode"], style=style, zoom=zoom,
        fit=fit if parts["mode"] == "image" else False,
        scroll=0.0 if parts["mode"] == "image" else scroll,
        base=parts["base"], can_go_back=can_go_back,
        with_mermaid=parts["with_mermaid"], vector=parts["vector"],
        view_box=parts["view_box"], tabs=tabs, active_tab=active_tab,
        sidebar=sidebar, font=font,
        csv=bool(parts.get("csv")), csv_align=csv_align,
        find_query=find_query,
    )


def render_welcome(style: str, tabs: list[dict] | None = None,
                   active_tab: int = 0, sidebar: dict | None = None,
                   font: str = "system") -> str:
    body = """
<div class="mdv-center"><div class="inner">
  <div class="glyph">&#128196;</div>
  <h1>Nothing open</h1>
  <p>Open a Markdown document, a Mermaid sketch, an SVG or an image.</p>
  <button id="pickFile">Open file&hellip;</button>
  <div class="shortcuts">
    <kbd class="hint">Ctrl</kbd>+<kbd class="hint">O</kbd> open &nbsp;&middot;&nbsp;
    <kbd class="hint">Ctrl</kbd>+<kbd class="hint">+</kbd> /
    <kbd class="hint">Ctrl</kbd>+<kbd class="hint">-</kbd> zoom &nbsp;&middot;&nbsp;
    <kbd class="hint">Ctrl</kbd>+<kbd class="hint">0</kbd> reset &nbsp;&middot;&nbsp;
    <kbd class="hint">F</kbd> fit &nbsp;&middot;&nbsp;
    <kbd class="hint">Ctrl</kbd>+<kbd class="hint">T</kbd> new tab &nbsp;&middot;&nbsp;
    <kbd class="hint">1</kbd> light <kbd class="hint">2</kbd> dark
    <kbd class="hint">3</kbd> github <kbd class="hint">4</kbd> github-ext
  </div>
</div></div>"""
    return build_page(
        body=body, title="md-view", mode="blank", style=style, zoom=1.0,
        fit=False, scroll=0.0, base=None, can_go_back=False, with_mermaid=False,
        tabs=tabs, active_tab=active_tab, sidebar=sidebar, font=font,
    )


def render_error(title: str, message: str, style: str,
                 tabs: list[dict] | None = None, active_tab: int = 0,
                 can_go_back: bool = True, sidebar: dict | None = None,
                 font: str = "system") -> str:
    body = (
        f'<div class="mdv-center"><div class="inner"><div class="glyph">&#9888;</div>'
        f"<h1>{html.escape(title)}</h1><p>{html.escape(message)}</p>"
        '<button id="pickFile">Open another file&hellip;</button>'
        "</div></div>"
    )
    return build_page(
        body=body, title=title, mode="blank", style=style, zoom=1.0, fit=False,
        scroll=0.0, base=None, can_go_back=can_go_back, with_mermaid=False,
        tabs=tabs, active_tab=active_tab, sidebar=sidebar, font=font,
    )


# --------------------------------------------------------------------------- #
# The application
# --------------------------------------------------------------------------- #

def _drop_stale_bridge_replies() -> None:
    """Silence pywebview's error for a bridge reply whose page is gone.

    Most bridge calls change what is on screen -- open, switch or close a tab --
    so they end in ``load_url``. pywebview then hands back the call's return
    value through a callback on the page that made the call, but only after
    waiting for the *new* page to load, which never registered that callback.
    Each such call therefore raised ``JavascriptException`` in a worker thread
    and printed a traceback. Nothing is lost by dropping it: the page that
    wanted the reply is gone, and ``call()`` in the page ignores replies
    anyway. Every other thread exception goes to the previous hook.
    """
    previous = threading.excepthook

    def hook(args: threading.ExceptHookArgs) -> None:
        exc = args.exc_value
        # Matched by name: webview is imported lazily, not at module level.
        if (type(exc).__name__ == "JavascriptException"
                and "_returnValuesCallbacks" in str(exc)):
            return
        previous(args)

    threading.excepthook = hook


class Tab:
    """One open document, with its own history and scroll position."""

    __slots__ = ("path", "history", "forward", "scroll")

    def __init__(self, path: Path | None):
        self.path = path
        self.history: list[Path] = []
        self.forward: list[Path] = []
        self.scroll = 0.0

    @property
    def title(self) -> str:
        return self.path.name if self.path else "Start"

    def describe(self, stale: bool = False) -> dict:
        return {
            "title": self.title,
            "path": str(self.path) if self.path else "",
            "stale": stale,
        }


class Viewer:
    """Owns the window, the open tabs and the file watcher.

    Threading. Navigation is triggered from three places: the UI thread, the JS
    bridge (a link click, a tab click) and the file watcher. Two locks keep that
    safe, and the order between them matters:

    ``_js``  serialises ``evaluate_js``.
    ``_nav`` guards tab state, page staging and window navigation. Everything
             it protects is fast and never waits on the page.

    ``_js`` is always taken *and released* before ``_nav``. Holding ``_nav``
    across an ``evaluate_js`` deadlocks: the result is delivered on the bridge
    thread, and that thread would itself be blocked waiting for ``_nav``.
    """

    def __init__(self, paths: list[Path] | Path | None = None, *, style: str, zoom: float,
                 watch: bool = True, mermaid: bool = True, debug: bool = False,
                 font: str = "system"):
        import tempfile
        import webview  # imported here so --register works without a GUI stack

        self.webview = webview
        self.prefs = config.load_prefs()
        self.style = style
        self.font = font if font in FONTS else "system"
        self.csv_align = bool(self.prefs.get("csv_align", False))
        # Kept for the session only: a repaint should not lose what you
        # were searching for, but it does not belong in prefs.
        self.find_query = ""
        self.zoom = zoom
        self.fit = bool(self.prefs.get("fit", True))
        self.watch_enabled = watch
        self.mermaid_enabled = mermaid
        self.debug = debug

        if isinstance(paths, (Path, str)):
            paths = [Path(paths)]          # a single document is the common case
        opening = [p for p in (paths or []) if p is not None]
        self.tabs: list[Tab] = [Tab(self._canon(p)) for p in opening] or [Tab(None)]
        self.active = 0

        self._tmpdir = Path(tempfile.mkdtemp(prefix="mdview-"))
        self._counter = 0
        self._bridge_key = None
        self._nav = threading.RLock()
        self._js = threading.RLock()
        self._mtimes: dict[Path, float] = {}
        self._stale: set[Path] = set()
        self._capture_failures = 0
        # Mermaid arrives in the background: the page that failed to get it from
        # the CDN is repainted once, when the cache fills (or at once if it has).
        self._mermaid_lock = threading.Lock()
        self._mermaid_missing = False
        self._mermaid_repainted = False

        # Sidebar state lives here, not in the page: every navigation rebuilds
        # the document, and expanded folders must survive that.
        self.sidebar_visible = bool(self.prefs.get("sidebar", True))
        self.sidebar_width = int(self.prefs.get("sidebar_width") or 264)
        self.docs_height = int(self.prefs.get("docs_height") or 220)
        self.panes = dict(self.prefs.get("panes") or {})
        self.doc_collapsed = self._canon_set(self.prefs.get("doc_collapsed"))
        # Node keys, not paths: entries saved by an older version carry no
        # root and are dropped rather than guessed at.
        self.expanded = {k for k in (self.prefs.get("expanded") or [])
                         if isinstance(k, str) and KEY_SEP in k}
        # Pinned for the session: see filesystem_roots. Opening a file must not
        # move the tree out from under the reader.
        self.fs_anchor = documents_anchor([t.path for t in self.tabs if t.path])
        if self.fs_anchor is not None:
            # start where the documents live
            self.expanded.add(node_key("anchor", self.fs_anchor))
        self._stop = threading.Event()
        self._window = None
        self._server = None

    # -- helpers ----------------------------------------------------------- #

    @staticmethod
    def _canon(path: Path | None) -> Path | None:
        """Canonical form, so the same file always compares equal.

        Paths arrive from the command line, from links, from another instance
        and from the file dialog, each with its own spelling (short names,
        mixed case, `..`).
        """
        if path is None:
            return None
        try:
            return path.resolve()
        except OSError:
            return path

    @staticmethod
    def _safe_mtime(path: Path | None) -> float | None:
        try:
            return path.stat().st_mtime if path else None
        except OSError:
            return None

    @property
    def tab(self) -> Tab:
        return self.tabs[self.active]

    @property
    def current(self) -> Path | None:
        return self.tab.path

    def _title(self, path: Path | None) -> str:
        extra = f" [{len(self.tabs)}]" if len(self.tabs) > 1 else ""
        return f"{path.name} - {APP_NAME}{extra}" if path else f"{APP_NAME}{extra}"

    def _stage(self, html_text: str) -> str:
        """Write HTML to a fresh temp file and return its file:// URL.

        A new name each time: navigating to the URL that is already loaded
        produces no navigation event, which would strand ``evaluate_js``.
        """
        import secrets

        self._counter += 1
        f = self._tmpdir / f"view-{self._counter:04d}.html"
        f.write_text(html_text, "utf-8")
        for old in self._tmpdir.glob("view-*.html"):
            try:
                if old != f and self._counter - int(old.stem.split("-")[1]) > 2:
                    old.unlink(missing_ok=True)
            except (ValueError, OSError):
                pass
        # Only the navigation initiated by Python carries the key. A file URL
        # fragment is omitted from referrers and never written into the HTML.
        # Repaints rotate it so previously staged pages lose access.
        self._bridge_key = secrets.token_urlsafe(32)
        return f"{f.as_uri()}#{self._bridge_key}"

    # -- page building ----------------------------------------------------- #

    def _tab_dicts(self) -> list[dict]:
        return [t.describe(stale=t.path is not None and t.path in self._stale)
                for t in self.tabs]

    def _sidebar(self) -> dict:
        """Everything the two trees need, resolved at page-build time."""
        try:
            files = build_fs_tree(self.fs_anchor, self.expanded)
        except Exception:
            files = []          # an unreadable drive must not blank the page
        return {
            "visible": self.sidebar_visible,
            "width": self.sidebar_width,
            "docs_height": self.docs_height,
            "panes": self.panes,
            "docs": build_doc_tree(self.tabs, self.active, self._stale,
                                   self.doc_collapsed),
            "files": files,
        }

    def _page_for(self, tab: Tab, scroll: float) -> str:
        tabs, active = self._tab_dicts(), self.active
        side = self._sidebar()
        path = tab.path
        if path is None:
            return render_welcome(self.style, tabs, active, side, self.font)
        try:
            if not path.exists():
                return render_error("File not found", str(path), self.style, tabs, active,
                                    can_go_back=bool(tab.history), sidebar=side,
                                    font=self.font)
            if path.is_dir():
                return render_error("That is a folder", str(path), self.style, tabs, active,
                                    can_go_back=bool(tab.history), sidebar=side,
                                    font=self.font)
            html_text = render_document(
                path, style=self.style, zoom=self.zoom, fit=self.fit,
                scroll=scroll, can_go_back=bool(tab.history),
                tabs=tabs, active_tab=active, sidebar=side, font=self.font,
                csv_align=self.csv_align, find_query=self.find_query,
            )
            if not self.mermaid_enabled:
                html_text = html_text.replace("__mdv_mermaidReady()", "void 0")
            return html_text
        except OSError as exc:
            return render_error("Cannot read this file", str(exc), self.style, tabs, active,
                                sidebar=side, font=self.font)
        except Exception as exc:  # a bad document must not take the viewer down
            if self.debug:
                import traceback
                traceback.print_exc()
            return render_error("Failed to render", f"{type(exc).__name__}: {exc}",
                                self.style, tabs, active, sidebar=side, font=self.font)

    def _paint(self, *, scroll: float | None = None) -> str:
        """Render the active tab into the window. Caller must hold _nav."""
        tab = self.tab
        if scroll is None:
            scroll = tab.scroll
        if tab.path is not None:
            mtime = self._safe_mtime(tab.path)
            if mtime is not None:
                self._mtimes[tab.path] = mtime
            self._stale.discard(tab.path)
        url = self._stage(self._page_for(tab, scroll))
        if self._window is not None:
            self._window.set_title(self._title(tab.path))
            self._window.load_url(url)
        return url

    def _capture_scroll(self) -> None:
        """Remember where the visible tab is scrolled to. Best effort only.

        pywebview waits on ``evaluate_js`` with no timeout, so a call that races
        a navigation can be stranded for good. Losing a scroll offset is
        cosmetic; a frozen window is not, so this gives up quickly and, after a
        few failures, stops asking altogether. Never holds ``_nav``.
        """
        window = self._window
        if window is None or self._capture_failures >= 3:
            return
        if not self._js.acquire(blocking=False):
            return  # a capture is already in flight; one sample is enough
        try:
            box: dict[str, object] = {}

            def ask() -> None:
                try:
                    box["value"] = window.evaluate_js(
                        "window.__mdv_scroll && window.__mdv_scroll()"
                    )
                except Exception:
                    box["value"] = None

            worker = threading.Thread(target=ask, daemon=True)
            worker.start()
            worker.join(1.5)
            if worker.is_alive():
                self._capture_failures += 1
                return
            self._capture_failures = 0
            try:
                self.tab.scroll = float(box.get("value") or 0.0)
            except (TypeError, ValueError):
                pass
        finally:
            self._js.release()

    # -- tabs -------------------------------------------------------------- #

    def open_tab(self, path: Path | None, *, focus: bool = True) -> int:
        """Open a document in a new tab, or focus the tab that already has it."""
        path = self._canon(path)
        self._capture_scroll()
        with self._nav:
            for index, tab in enumerate(self.tabs):
                if tab.path == path and path is not None:
                    self.active = index
                    self._paint()
                    return index
            # An untouched Start tab is a placeholder: reuse it.
            if len(self.tabs) == 1 and self.tabs[0].path is None:
                self.tabs[0] = Tab(path)
                self.active = 0
            else:
                self.tabs.insert(self.active + 1, Tab(path))
                if focus:
                    self.active += 1
            self._paint()
            return self.active

    def select_tab(self, index: int) -> None:
        self._capture_scroll()
        with self._nav:
            if not 0 <= index < len(self.tabs) or index == self.active:
                return
            self.active = index
            self._paint()

    def close_tab(self, index: int = -1) -> None:
        self._capture_scroll()
        with self._nav:
            if index < 0:
                index = self.active
            if not 0 <= index < len(self.tabs):
                return
            if len(self.tabs) == 1:
                # Last tab: close the window, the way a browser would.
                if self._window is not None:
                    self._window.destroy()
                return
            gone = self.tabs.pop(index)
            if gone.path is not None and not any(t.path == gone.path for t in self.tabs):
                self._mtimes.pop(gone.path, None)
                self._stale.discard(gone.path)
            if self.active > index or self.active >= len(self.tabs):
                self.active = max(0, self.active - 1)
            self._paint()

    def next_tab(self) -> None:
        self.select_tab((self.active + 1) % len(self.tabs))

    def prev_tab(self) -> None:
        self.select_tab((self.active - 1) % len(self.tabs))

    # -- navigation within a tab ------------------------------------------- #

    def show(self, path: Path | None, *, scroll: float = 0.0, record: bool = True):
        """Point the active tab at `path`."""
        path = self._canon(path)
        with self._nav:
            tab = self.tab
            if record and tab.path is not None and tab.path != path:
                tab.history.append(tab.path)
                tab.forward.clear()
            tab.path = path
            tab.scroll = scroll
            return self._paint(scroll=scroll)

    def go_back(self) -> None:
        with self._nav:
            tab = self.tab
            if not tab.history:
                return
            target = tab.history.pop()
            if tab.path:
                tab.forward.append(tab.path)
            tab.path = target
            tab.scroll = 0.0
            self._paint(scroll=0.0)

    def go_forward(self) -> None:
        with self._nav:
            tab = self.tab
            if not tab.forward:
                return
            target = tab.forward.pop()
            if tab.path:
                tab.history.append(tab.path)
            tab.path = target
            tab.scroll = 0.0
            self._paint(scroll=0.0)

    def refresh(self) -> None:
        """Rebuild the active tab from disk, keeping the scroll position."""
        self._capture_scroll()
        with self._nav:
            if self.tab.path is not None:
                invalidate_document(self.tab.path)
            self._paint()

    def mermaid_missing(self) -> None:
        """The page found no mermaid.js. Repaint once the cache has it."""
        with self._mermaid_lock:
            if self._mermaid_repainted:
                return
            if mermaid_assets.find_mermaid() is None:
                self._mermaid_missing = True
                return
            self._mermaid_repainted = True
        self.refresh()

    def mermaid_arrived(self) -> None:
        """The background download finished: repaint only if a page needed it."""
        with self._mermaid_lock:
            if not (self._mermaid_missing and mermaid_assets.find_mermaid()) or self._mermaid_repainted:
                return
            self._mermaid_missing = False
            self._mermaid_repainted = True
        self.refresh()

    def open_path(self, raw: str, *, new_tab: bool = False) -> bool:
        """Open a link target: viewable files in-app, anything else via the OS."""
        base = self.current.parent if self.current else Path.cwd()
        path = links._path_from_href(raw, base)
        if path is None:
            return False
        # Before is_dir() or any read: a document must not make this PC sign in
        # to another computer just because the reader clicked a link.
        if links._is_network_path(path) and not (self._window is not None and self._window.create_confirmation_dialog(
                APP_NAME, f"This link reads from another computer on the network.\n"
                          f"Windows may send your sign-in to it.\n\n{path}\n\nOpen it?")):
            return False
        # On macOS a folder with an extension may be a bundle (.app, .prefPane)
        # that `open` launches, so it is asked about below like a program.
        if path.is_dir() and not (config._IS_MAC and path.suffix):
            links._os_open(path)
            return False
        if path.suffix.lower() in VIEWABLE_EXTS:
            if new_tab:
                self.open_tab(path)
            else:
                self.show(path)
            return True
        # Asked every time, as a browser does for a download: the link may be
        # a program, and the request may come from a page rather than a click.
        if self._window is not None and self._window.create_confirmation_dialog(
                APP_NAME, f"md-view cannot show {path.name}.\n\n"
                          f"Open it with its default app?\n\n{path}"):
            links._os_open(path)
        return False

    def _raise(self) -> None:
        """Bring the window forward without touching its geometry.

        Only for files arriving from *another process*; opening a tab from
        inside the window must never disturb it.

        Deliberately not window.restore(): that sets WindowState to Normal,
        which un-maximises. show() is Show() + Activate(), which leaves the
        window state, size and position exactly as the user left them.
        """
        if self._window is None:
            return
        try:
            self._window.show()
        except Exception:
            pass

    # -- file watching ----------------------------------------------------- #

    def _watch_loop(self) -> None:
        """Reload the visible tab when its file changes; flag the others."""
        while not self._stop.wait(0.7):
            # Under the lock: close_tab pops a tab one step before it fixes
            # self.active, and reading self.current in between raised
            # IndexError here, which ended the watcher for the session.
            with self._nav:
                watched = [t.path for t in self.tabs if t.path is not None]
                active_path = self.current
            for path in dict.fromkeys(watched):
                known = self._mtimes.get(path)
                if known is None:
                    continue
                now = self._safe_mtime(path)
                if now is None or now == known:
                    continue
                time.sleep(0.15)  # let a slow writer finish
                if self._safe_mtime(path) != now:
                    continue
                self._mtimes[path] = now
                invalidate_document(path)
                if path == active_path:
                    try:
                        self.refresh()
                    except Exception:
                        pass
                else:
                    # Mark it and repaint so the tab shows its dot.
                    self._stale.add(path)
                    with self._nav:
                        try:
                            self._paint()
                        except Exception:
                            pass

    # -- lifecycle --------------------------------------------------------- #

    def run(self) -> None:
        import shutil
        from hmac import compare_digest

        api = Api(self)
        # Every public Api method, read from the class so that adding or
        # deleting one there can never leave this table naming a missing method.
        actions = {name: getattr(api, name) for name in dir(api)
                   if not name.startswith("_") and callable(getattr(api, name))}

        def dispatch(key, action, args):
            current_key = self._bridge_key
            if (current_key is None or not isinstance(key, str) or not key.isascii()
                    or not compare_digest(key, current_key)
                    or not isinstance(action, str) or not isinstance(args, list)):
                return None
            handler = actions.get(action)
            return handler(*args) if handler is not None else None

        with self._nav:
            start_url = self._stage(self._page_for(self.tab, 0.0))
            if self.tab.path is not None:
                mtime = self._safe_mtime(self.tab.path)
                if mtime is not None:
                    self._mtimes[self.tab.path] = mtime
        bg = STYLE_BG.get(self.style, "#ffffff")

        self._window = self.webview.create_window(
            self._title(self.current),
            url=start_url,
            width=1100, height=820, min_size=(420, 320),
            background_color=bg,
            text_select=True,
            zoomable=False,          # we manage zoom ourselves so the chrome stays fixed
            easy_drag=False,
        )
        api._window = self._window
        # Use an explicit function rather than giving pywebview a traversable
        # js_api object. The dispatcher checks the key on every call.
        self._window.expose(dispatch)

        def on_start():
            if self.watch_enabled:
                threading.Thread(target=self._watch_loop, daemon=True).start()

        _drop_stale_bridge_replies()
        try:
            # Private mode keeps each process on its own ephemeral profile, so
            # a second launch never contends for a shared WebView2 user-data
            # folder. Preferences live in prefs.json on the Python side.
            self.webview.start(on_start, debug=self.debug)
        finally:
            self._stop.set()
            if self._server is not None:
                self._server.close()
            self._persist()
            shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _persist(self) -> None:
        self.prefs.update({
            "style": self.style, "style_default": DEFAULT_STYLE,
            "zoom": round(self.zoom, 4), "fit": self.fit,
            "font": self.font, "csv_align": self.csv_align,
            "sidebar": self.sidebar_visible, "sidebar_width": self.sidebar_width,
            "docs_height": self.docs_height, "panes": self.panes,
            # Keep the list bounded: an unbounded set would grow forever.
            "expanded": sorted(list(self.expanded)[:400]),
            "doc_collapsed": sorted(str(p) for p in list(self.doc_collapsed)[:200]),
        })
        config.save_prefs(self.prefs)

    # -- sidebar ----------------------------------------------------------- #

    def set_expanded(self, keys: list[str]) -> None:
        """Replace the expanded set from the page.

        These are node keys the page got from us, so they round-trip exactly;
        no normalising is needed or wanted.
        """
        self.expanded = {k for k in (keys or []) if isinstance(k, str) and KEY_SEP in k}
        self._persist()

    @classmethod
    def _canon_set(cls, paths) -> set[Path]:
        """Canonical paths, so a folder compares equal however it was spelled."""
        fresh: set[Path] = set()
        for item in paths or []:
            if not item:
                continue
            try:
                canon = cls._canon(Path(item))
            except (TypeError, ValueError, OSError):
                continue
            if canon is not None:
                fresh.add(canon)
        return fresh

    def set_doc_collapsed(self, paths: list[str]) -> None:
        """Replace the set of folders collapsed in the open-documents tree."""
        self.doc_collapsed = self._canon_set(paths)
        self._persist()

    def open_from_tree(self, raw: str) -> bool:
        """Open a file picked in the computer tree, always in its own tab."""
        try:
            path = Path(raw)
        except (TypeError, ValueError):
            return False
        if path.is_dir():
            return False        # folders are expanded by the tree, not opened
        if not path.exists():
            return False
        if path.suffix.lower() in VIEWABLE_EXTS:
            self.open_tab(path)
            return True
        return False            # the tree lists only viewable files

    def toggle_csv_align(self) -> bool:
        """Alignment changes the rendered text, so the tab is rebuilt."""
        self.csv_align = not self.csv_align
        self._persist()
        self._capture_scroll()
        with self._nav:
            self._paint()
        return self.csv_align

    def reveal_current(self) -> bool:
        """Expand down to the active document under every root holding it."""
        path = self.current
        if path is None:
            return False
        for root in filesystem_roots(self.fs_anchor):
            root_path = Path(root["path"])
            if not _is_under(path, root_path):
                continue
            cursor = path.parent
            while True:
                self.expanded.add(node_key(root["root"], cursor))
                if _same_path(cursor, root_path) or cursor == cursor.parent:
                    break
                cursor = cursor.parent
        self._persist()
        with self._nav:
            self._paint()
        return True


class Api:
    """Viewer actions available through the authenticated dispatcher.

    These run on the JS bridge thread. None of them may block on the page.
    """

    def __init__(self, viewer: Viewer):
        self._viewer = viewer
        self._window = None

    # navigation
    def go_back(self):
        self._viewer.go_back()

    def go_forward(self):
        self._viewer.go_forward()

    def refresh(self):
        self._viewer.refresh()

    def mermaid_missing(self):
        self._viewer.mermaid_missing()

    def open_path(self, href: str):
        return self._viewer.open_path(href)

    def open_external(self, url: str):
        if re.match(r"^(https?|ftp|mailto):", url, re.IGNORECASE):
            import webbrowser
            webbrowser.open(url)

    # tabs
    def select_tab(self, index: int):
        try:
            self._viewer.select_tab(int(index))
        except (TypeError, ValueError):
            pass

    def close_tab(self, index: int = -1):
        try:
            self._viewer.close_tab(int(index))
        except (TypeError, ValueError):
            pass

    def next_tab(self):
        self._viewer.next_tab()

    def prev_tab(self):
        self._viewer.prev_tab()

    def new_tab(self):
        return self.pick_file(new_tab=True)

    def pick_file(self, new_tab: bool = False):
        if self._window is None:
            return None
        types = (
            "Viewable files (*.md;*.markdown;*.mmd;*.mermaid;*.svg;*.png;*.jpg;*.jpeg;*.gif;*.webp;*.bmp)",
            "Markdown (*.md;*.markdown;*.mdown;*.mkd)",
            "Mermaid (*.mmd;*.mermaid)",
            "Images (*.png;*.jpg;*.jpeg;*.gif;*.webp;*.bmp;*.ico;*.svg)",
            "All files (*.*)",
        )
        current = self._viewer.current
        start = str(current.parent) if current else ""
        result = self._window.create_file_dialog(
            self._viewer.webview.OPEN_DIALOG, directory=start,
            allow_multiple=True, file_types=types,
        )
        if not result:
            return None
        chosen = [Path(r) for r in result]
        if new_tab or len(chosen) > 1 or self._viewer.current is not None:
            for path in chosen:
                self._viewer.open_tab(path)
        else:
            self._viewer.show(chosen[0])
        return str(chosen[0])

    # sidebar trees
    def list_dir(self, path: str):
        """Children of a folder, for lazy expansion. Never raises into JS."""
        try:
            target = Path(path)
            if not target.is_dir():
                return {"path": path, "entries": [], "more": 0, "denied": True}
            entries, more = dir_entries(target)
            return {"path": path, "entries": entries, "more": more, "denied": False}
        except (OSError, ValueError):
            return {"path": path, "entries": [], "more": 0, "denied": True}

    def set_expanded(self, paths: list):
        self._viewer.set_expanded(list(paths or []))
        return True

    def set_doc_collapsed(self, paths: list):
        self._viewer.set_doc_collapsed(list(paths or []))
        return True

    def open_from_tree(self, path: str):
        return self._viewer.open_from_tree(path)

    def set_sidebar(self, visible: bool = True, width: int = 0, panes: dict | None = None,
                    docs_height: int = 0):
        viewer = self._viewer
        viewer.sidebar_visible = bool(visible)
        try:
            if width:
                viewer.sidebar_width = max(160, min(640, int(width)))
        except (TypeError, ValueError):
            pass
        try:
            if docs_height:
                viewer.docs_height = max(60, min(1200, int(docs_height)))
        except (TypeError, ValueError):
            pass
        if isinstance(panes, dict):
            viewer.panes = {k: bool(v) for k, v in panes.items()}
        viewer._persist()
        return True

    def reveal_active(self):
        """Expand the computer tree down to the document on screen."""
        return self._viewer.reveal_current()

    # window
    def toggle_fullscreen(self):
        if self._window is not None:
            self._window.toggle_fullscreen()

    def set_find_query(self, query: str):
        """Remember the search text so a repaint can put it back."""
        try:
            self._viewer.find_query = str(query or "")[:200]
        except (TypeError, ValueError):
            self._viewer.find_query = ""
        return True

    def set_font(self, name: str):
        """Change the body typeface. CSS-only, so no repaint is needed."""
        if name not in FONTS:
            return False
        self._viewer.font = name
        self._viewer._persist()
        return True

    def toggle_csv_align(self):
        """Flip column alignment and rebuild the view."""
        return self._viewer.toggle_csv_align()

    # preferences
    def save_view_prefs(self, state: dict):
        try:
            if "zoom" in state:
                self._viewer.zoom = float(state["zoom"])
            if state.get("style") in STYLES:
                self._viewer.style = state["style"]
            if "fit" in state:
                self._viewer.fit = bool(state["fit"])
        except (TypeError, ValueError):
            return False
        self._viewer._persist()
        return True


# --------------------------------------------------------------------------- #
# Single instance: hand new files to the window that is already open
# --------------------------------------------------------------------------- #

class InstanceServer:
    """A loopback listener that accepts paths from later launches."""

    def __init__(self, viewer: Viewer):
        import secrets

        self.viewer = viewer
        self.token = secrets.token_hex(16)
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(8)
        self.port = self._sock.getsockname()[1]
        self._closed = False
        self._record()
        threading.Thread(target=self._serve, daemon=True).start()

    def _record(self) -> None:
        payload = {"port": self.port, "token": self.token, "pid": os.getpid()}
        try:
            instance_file().write_text(json.dumps(payload), "utf-8")
        except OSError:
            pass

    def _serve(self) -> None:
        while not self._closed:
            try:
                conn, _ = self._sock.accept()
            except OSError:
                return
            with conn:
                try:
                    conn.settimeout(5)
                    raw = conn.recv(65536).decode("utf-8", errors="replace")
                    message = json.loads(raw or "{}")
                    # The token stops anything else on the machine from
                    # driving this window.
                    if message.get("token") != self.token:
                        conn.sendall(b"denied")
                        continue
                    paths = [Path(item) for item in message.get("paths") or []]
                    paths = [p for p in paths if p.exists()]
                    # Answer before opening: opening can outlast the sender's
                    # timeout, and a sender that gives up opens a second window.
                    conn.sendall(b"ok" if paths else b"empty")
                    for path in paths:
                        try:
                            self.viewer.open_tab(path)
                        except OSError as exc:      # one bad file must not drop the rest
                            print(f"{APP_NAME}: could not open {path}: {exc}", file=sys.stderr)
                    if paths:
                        # Only a hand-off from another process brings the
                        # window forward; in-app opens leave it alone.
                        self.viewer._raise()
                except (OSError, ValueError, TypeError):
                    continue

    def close(self) -> None:
        self._closed = True
        try:
            self._sock.close()
        except OSError:
            pass
        try:
            current = json.loads(instance_file().read_text("utf-8"))
            if current.get("pid") == os.getpid():
                instance_file().unlink(missing_ok=True)
        except (OSError, ValueError):
            pass


def instance_file() -> Path:
    return config.data_dir() / "instance.json"


def instance_lock():
    """Take the per-user lock that marks the window owner; None if it is held.

    Launches that start together (several files opened at once from Explorer)
    would all find no running window; the lock lets exactly one become it.
    The OS drops the lock when its process exits, so a crash never leaves it
    stale. The returned handle must stay referenced while the window is open.
    """
    try:
        handle = open(config.data_dir() / "instance.lock", "a+b")
    except OSError:
        return True     # no lock file possible: every launch may own a window, as before
    try:
        handle.seek(0)
        if sys.platform == "win32":
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return handle
    except OSError as exc:
        handle.close()
        # Only "someone else holds it" means another viewer owns the window.
        # msvcrt reports that as EACCES (EDEADLOCK from the blocking form).
        if isinstance(exc, BlockingIOError) or (
                sys.platform == "win32" and exc.errno in (errno.EACCES, errno.EDEADLK)):
            return None
        # Any other failure (ENOLCK, ...) would make every launch wait for an
        # owner that never comes; open a window without the lock instead.
        print(f"{APP_NAME}: cannot take the instance lock ({exc})", file=sys.stderr)
        return True


def hand_off(paths: list[Path], timeout: float = 2.0) -> bool:
    """Ask a running viewer to open these paths. True when it accepted."""
    try:
        info = json.loads(instance_file().read_text("utf-8"))
        port, token = int(info["port"]), str(info["token"])
    except (OSError, ValueError, KeyError, TypeError):
        return False
    payload = json.dumps({"token": token, "paths": [str(p) for p in paths]})
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout) as sock:
            sock.settimeout(timeout)
            sock.sendall(payload.encode("utf-8"))
            return sock.recv(16).startswith(b"ok")
    except OSError:
        # Stale record: the previous instance is gone.
        return False

# --------------------------------------------------------------------------- #
# Windows file associations
# --------------------------------------------------------------------------- #

PROGIDS = {
    "markdown": ("md-view.markdown", "Markdown Document", sorted(MARKDOWN_EXTS)),
    "mermaid": ("md-view.mermaid", "Mermaid Diagram", sorted(MERMAID_EXTS)),
}
CONTEXT_MENU_EXTS = sorted(MARKDOWN_EXTS | MERMAID_EXTS | IMAGE_EXTS)
VERB_KEY = "md-view.open"


def _launch_command() -> tuple[str, str]:
    """Return (command, icon) for the registry, preferring a console-free launcher."""
    script = Path(__file__).resolve()
    exe = Path(sys.executable)
    pythonw = exe.with_name("pythonw.exe")
    launcher = pythonw if pythonw.is_file() else exe
    return f'"{launcher}" "{script}" "%1"', f'"{launcher}",0'


def register_associations() -> int:
    if sys.platform != "win32":
        print("--register currently supports Windows only.", file=sys.stderr)
        print("On Linux, install a .desktop file; on macOS, use a small app bundle.", file=sys.stderr)
        return 2

    import winreg

    command, icon = _launch_command()
    classes = r"Software\Classes"
    created = []

    def setval(root, sub, name, value, vtype=winreg.REG_SZ):
        with winreg.CreateKeyEx(root, sub, 0, winreg.KEY_WRITE) as key:
            winreg.SetValueEx(key, name, 0, vtype, value)

    for progid, label, exts in PROGIDS.values():
        setval(winreg.HKEY_CURRENT_USER, rf"{classes}\{progid}", "", label)
        setval(winreg.HKEY_CURRENT_USER, rf"{classes}\{progid}", "FriendlyTypeName", label)
        setval(winreg.HKEY_CURRENT_USER, rf"{classes}\{progid}\DefaultIcon", "", icon)
        setval(winreg.HKEY_CURRENT_USER, rf"{classes}\{progid}\shell\open", "", f"View with {APP_NAME}")
        setval(winreg.HKEY_CURRENT_USER, rf"{classes}\{progid}\shell\open\command", "", command)
        for ext in exts:
            # Default handler: honoured when the user has no explicit UserChoice.
            setval(winreg.HKEY_CURRENT_USER, rf"{classes}\{ext}", "", progid)
            # And always offer it in the "Open with" list.
            with winreg.CreateKeyEx(
                winreg.HKEY_CURRENT_USER, rf"{classes}\{ext}\OpenWithProgids", 0, winreg.KEY_WRITE
            ) as key:
                winreg.SetValueEx(key, progid, 0, winreg.REG_NONE, b"")
            created.append(ext)

    # A right-click verb, so the viewer is reachable even for types whose
    # default handler we deliberately leave alone (images, SVG).
    for ext in CONTEXT_MENU_EXTS:
        base = rf"{classes}\SystemFileAssociations\{ext}\shell\{VERB_KEY}"
        setval(winreg.HKEY_CURRENT_USER, base, "", f"View with {APP_NAME}")
        setval(winreg.HKEY_CURRENT_USER, base, "Icon", icon)
        setval(winreg.HKEY_CURRENT_USER, rf"{base}\command", "", command)

    _notify_shell()
    print(f"Registered {APP_NAME} for: {', '.join(created)}")
    print(f"Right-click 'View with {APP_NAME}' added for: {', '.join(CONTEXT_MENU_EXTS)}")
    print(f"Command: {command}")
    print()
    print("If Windows still opens another app for .md, that extension already has a")
    print("saved UserChoice. Fix it once via right-click > Open with > Choose another")
    print(f"app > {APP_NAME} > Always.")
    return 0


def unregister_associations() -> int:
    if sys.platform != "win32":
        print("--unregister currently supports Windows only.", file=sys.stderr)
        return 2

    import winreg

    classes = r"Software\Classes"

    def delete_tree(root, sub):
        try:
            with winreg.OpenKey(root, sub, 0, winreg.KEY_READ | winreg.KEY_WRITE) as key:
                while True:
                    try:
                        child = winreg.EnumKey(key, 0)
                    except OSError:
                        break
                    delete_tree(root, f"{sub}\\{child}")
            winreg.DeleteKey(root, sub)
            return True
        except FileNotFoundError:
            return False
        except OSError:
            return False

    removed = []
    for progid, _label, exts in PROGIDS.values():
        if delete_tree(winreg.HKEY_CURRENT_USER, rf"{classes}\{progid}"):
            removed.append(progid)
        for ext in exts:
            # Only reset the default if it still points at us.
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, rf"{classes}\{ext}", 0,
                                    winreg.KEY_READ | winreg.KEY_WRITE) as key:
                    try:
                        value, _ = winreg.QueryValueEx(key, "")
                    except FileNotFoundError:
                        value = None
                    if value == progid:
                        winreg.DeleteValue(key, "")
            except FileNotFoundError:
                pass
            except OSError:
                pass
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, rf"{classes}\{ext}\OpenWithProgids",
                                    0, winreg.KEY_READ | winreg.KEY_WRITE) as key:
                    winreg.DeleteValue(key, progid)
            except (FileNotFoundError, OSError):
                pass

    for ext in CONTEXT_MENU_EXTS:
        delete_tree(winreg.HKEY_CURRENT_USER,
                    rf"{classes}\SystemFileAssociations\{ext}\shell\{VERB_KEY}")

    _notify_shell()
    print(f"Removed: {', '.join(removed) if removed else 'nothing was registered'}")
    return 0


def _notify_shell() -> None:
    """Tell Explorer that association data changed."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        SHCNE_ASSOCCHANGED, SHCNF_IDLIST = 0x08000000, 0x0000
        ctypes.windll.shell32.SHChangeNotify(SHCNE_ASSOCCHANGED, SHCNF_IDLIST, None, None)
    except Exception:
        pass


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="md-view",
        description="Lightweight native viewer for Markdown, Mermaid, SVG and images.",
        epilog=(
            "Shortcuts: Ctrl++/Ctrl+- zoom, Ctrl+0 reset, F fit, W wide, "
            "F5 reload, Ctrl+F find, Ctrl+O open, Ctrl+B sidebar, "
            "Ctrl+D cycles style (or 1-4), "
            "[ back, F11 fullscreen."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("file", nargs="*", help="documents, sketches or images to display")
    p.add_argument("--zoom", type=float, metavar="F", help="initial zoom factor, e.g. 1.25")
    look = p.add_mutually_exclusive_group()
    look.add_argument("--style", choices=STYLES, dest="style",
                      help="presentation style (default: remembered, else github-ext)")
    look.add_argument("--dark", action="store_const", const="dark", dest="style",
                      help="shorthand for --style dark")
    look.add_argument("--light", action="store_const", const="light", dest="style",
                      help="shorthand for --style light")
    look.add_argument("--github", action="store_const", const="github", dest="style",
                      help="shorthand for --style github")
    look.add_argument("--github-ext", action="store_const", const="github-ext",
                      dest="style", help="shorthand for --style github-ext")
    p.add_argument("--font", choices=FONTS, dest="font",
                   help="body typeface (default: remembered, else the style's own)")
    p.add_argument("--no-watch", action="store_true",
                   help="do not reload when the file changes on disk")
    p.add_argument("--no-mermaid", action="store_true", help="skip mermaid rendering")
    p.add_argument("--register", action="store_true",
                   help="associate .md/.mmd with this viewer and add a right-click verb (Windows)")
    p.add_argument("--unregister", action="store_true", help="undo --register")
    p.add_argument("--fetch-assets", action="store_true",
                   help="download mermaid.js into the user cache for offline use")
    p.add_argument("--force", action="store_true", help="with --fetch-assets, re-download")
    p.add_argument("--new-window", action="store_true",
                   help="always start a separate window instead of adding a tab "
                        "to the running viewer")
    p.add_argument("--debug", action="store_true", help="open devtools and print tracebacks")
    p.add_argument("--version", action="version", version=f"{APP_NAME} {__version__}")
    return p


def _warm_renderers() -> None:
    """Import the markdown stack and build the highlight CSS, off the main thread."""
    try:
        markdown_render._markdown_module()
        styles.pygments_css()
    except Exception:
        pass        # purely a head start; the real render reports any problem


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.register:
        return register_associations()
    if args.unregister:
        return unregister_associations()
    if args.fetch_assets:
        return 0 if mermaid_assets.fetch_mermaid(force=args.force) else 1

    prefs = config.load_prefs()
    style = config.resolve_style(args.style, prefs)
    font = args.font or prefs.get("font") or "system"
    if font not in FONTS:
        font = "system"
    zoom = args.zoom or float(prefs.get("zoom") or 1.0)
    zoom = min(ZOOM_STEPS[-1], max(ZOOM_STEPS[0], zoom))

    paths: list[Path] = []
    for item in args.file:
        path = Path(item).expanduser()
        try:
            path = path.resolve()
        except OSError:
            pass
        if not path.exists():
            print(f"{APP_NAME}: no such file: {path}", file=sys.stderr)
            return 1
        paths.append(path)

    # A viewer already running? Give it the files as new tabs instead of
    # starting a second window -- this is the common case when documents are
    # opened one after another from Explorer. When the owner is still starting
    # up, keep trying until its listener answers; the lock is released if the owner
    # dies, so the wait always ends, and giving up early would open a second window.
    owner = None if args.new_window else instance_lock()
    if paths and not args.new_window:
        while True:
            if hand_off(paths):
                return 0
            if owner is not None:
                break
            # A file deleted since the startup check would make the owner reply
            # "empty" for ever; stop once none is left.
            for gone in [p for p in paths if not p.exists()]:
                print(f"{APP_NAME}: no such file: {gone}", file=sys.stderr)
            paths = [p for p in paths if p.exists()]
            if not paths:
                return 1
            time.sleep(0.2)
            owner = instance_lock()     # the owner may have quit meanwhile

    # pywebview takes a few hundred milliseconds to import (it loads the .NET
    # bridge on Windows). Pull markdown and pygments in alongside it, so the
    # first document is ready to render the moment the window can show it.
    threading.Thread(target=_warm_renderers, daemon=True).start()
    try:
        import webview  # noqa: F401
    except ImportError:
        print(
            "pywebview is not installed. Run:\n"
            "    pip install -r requirements.txt\n"
            "or  pip install .",
            file=sys.stderr,
        )
        return 1

    viewer = Viewer(
        paths, style=style, zoom=zoom, font=font,
        watch=not args.no_watch, mermaid=not args.no_mermaid, debug=args.debug,
    )
    # Grab mermaid the first time it is actually needed, so the very first
    # launch of a diagram is not silently broken.
    if not args.no_mermaid and mermaid_assets.find_mermaid() is None:
        def wants_mermaid(p: Path) -> bool:
            kind = classify(p)
            if kind == "mermaid":
                return True
            return kind == "markdown" and "mermaid" in read_text(p).lower()

        if any(wants_mermaid(p) for p in paths):
            # In the background: on a network that drops the CDN this would hold
            # the window back for the whole timeout, on every launch. This
            # launch loads mermaid from the CDN instead (see build_page); when
            # the download lands, a page the CDN failed is repainted.
            def fetch_then_repaint() -> None:
                if mermaid_assets.fetch_mermaid(timeout=30, quiet=True):
                    viewer.mermaid_arrived()

            threading.Thread(target=fetch_then_repaint, daemon=True).start()

    if not args.new_window:
        try:
            viewer._server = InstanceServer(viewer)
        except OSError as exc:
            # Without a listener we simply lose single-instance behaviour.
            print(f"{APP_NAME}: single-instance listener unavailable ({exc})", file=sys.stderr)
            # Nobody can reach this window, so do not keep later launches waiting for it.
            if hasattr(owner, "close"):
                owner.close()
            owner = None
    viewer.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
