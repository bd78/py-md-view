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

__version__ = "1.0.0"
APP_NAME = "md-view"

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

MERMAID_CDN = "https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js"

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


def save_prefs(prefs: dict) -> None:
    try:
        (PREFS_PATH or data_dir() / "prefs.json").write_text(
            json.dumps(prefs, indent=2), "utf-8"
        )
    except Exception:
        pass  # preferences are a convenience, never a failure mode


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


# --------------------------------------------------------------------------- #
# Mermaid asset management
# --------------------------------------------------------------------------- #

def vendored_mermaid() -> Path | None:
    """A mermaid.min.js shipped next to this script wins over the cache."""
    local = Path(__file__).resolve().parent / "assets" / "mermaid.min.js"
    return local if local.is_file() and local.stat().st_size > 100_000 else None


def cached_mermaid() -> Path | None:
    p = assets_dir() / "mermaid.min.js"
    return p if p.is_file() and p.stat().st_size > 100_000 else None


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

    target = assets_dir() / "mermaid.min.js"
    tmp = target.with_suffix(".part")
    try:
        if not quiet:
            print(f"Downloading mermaid.js from {MERMAID_CDN} ...", file=sys.stderr)
        req = urllib.request.Request(MERMAID_CDN, headers={"User-Agent": f"{APP_NAME}/{__version__}"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
        if len(data) < 100_000:
            raise ValueError(f"suspiciously small payload ({len(data)} bytes)")
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


# --------------------------------------------------------------------------- #
# Markdown -> HTML
# --------------------------------------------------------------------------- #

def _markdown_module():
    try:
        import markdown
        return markdown
    except ImportError:
        return None


MERMAID_FENCE = re.compile(
    r"^(?P<indent>[ ]{0,3})(?P<fence>`{3,}|~{3,})[ ]*"
    r"(?:\{[ ]*\.?)?(?P<lang>mermaid)\b[^\n]*$",
    re.IGNORECASE,
)


def _build_mermaid_extension(markdown_mod):
    """A preprocessor that lifts ```mermaid fences out before any other parsing.

    Doing it at preprocessor level keeps the diagram source pristine: no
    smart-quoting, no syntax highlighting, no entity mangling of `-->` arrows.
    """
    from markdown.extensions import Extension
    from markdown.preprocessors import Preprocessor

    class MermaidPreprocessor(Preprocessor):
        def run(self, lines):
            out, i = [], 0
            while i < len(lines):
                m = MERMAID_FENCE.match(lines[i])
                if not m:
                    out.append(lines[i])
                    i += 1
                    continue
                fence = m.group("fence")
                indent = len(m.group("indent"))
                close = re.compile(r"^[ ]{0,3}" + fence[0] + "{" + str(len(fence)) + r",}[ ]*$")
                body, i = [], i + 1
                while i < len(lines) and not close.match(lines[i]):
                    body.append(lines[i][indent:] if lines[i][:indent].isspace() else lines[i])
                    i += 1
                i += 1  # consume the closing fence (or run off the end)
                out.append(self.md.htmlStash.store(mermaid_block("\n".join(body))))
            return out

    class MermaidExtension(Extension):
        def extendMarkdown(self, md):
            # 30 = normalize_whitespace, 25 = fenced_code: sit in between.
            md.preprocessors.register(MermaidPreprocessor(md), "mdview_mermaid", 27)

    return MermaidExtension()


def mermaid_block(source: str) -> str:
    """Wrap mermaid source in the element mermaid.js looks for."""
    escaped = html.escape(source.strip(), quote=True)
    return (
        '<div class="mermaid-figure">'
        f'<pre class="mermaid" data-src="{escaped}">{escaped}</pre>'
        "</div>"
    )


TASK_ITEM = re.compile(r"<li>(\s*)\[([ xX])\]\s+")
RAW_META = re.compile(r"<meta(?=[\t\n\f\r />])", re.IGNORECASE)


def _task_lists(html_text: str) -> str:
    def sub(m):
        checked = " checked" if m.group(2).lower() == "x" else ""
        return f'<li class="task-item"><input type="checkbox" disabled{checked}> '
    return TASK_ITEM.sub(sub, html_text)


def render_markdown(text: str) -> tuple[str, str]:
    """Return (html_body, toc_html)."""
    markdown_mod = _markdown_module()
    if markdown_mod is None:
        return (
            '<div class="mdv-error"><h1>Missing dependency</h1>'
            "<p><code>markdown</code> is not installed. Run:</p>"
            "<pre><code>pip install markdown pygments</code></pre></div>",
            "",
        )

    extensions = [
        "extra",        # tables, fenced_code, footnotes, attr_list, def_list, abbr, md_in_html
        "toc",
        "sane_lists",
        "admonition",
        _build_mermaid_extension(markdown_mod),
    ]
    extension_configs = {"toc": {"permalink": "", "toc_depth": "2-4"}}

    try:
        import pygments  # noqa: F401
        extensions.append("codehilite")
        extension_configs["codehilite"] = {"guess_lang": False, "css_class": "codehilite"}
    except ImportError:
        pass

    md = markdown_mod.Markdown(extensions=extensions, extension_configs=extension_configs)
    body = _task_lists(md.convert(text))
    # CSP controls script execution, but does not block meta refresh. HTML
    # keeps the first copy of an attribute; make raw meta pragmas inert without
    # re-parsing the rest of the document or touching escaped code examples.
    body = RAW_META.sub('<meta http-equiv=""', body)
    return body, getattr(md, "toc", "")


# --------------------------------------------------------------------------- #
# Link / image rewriting so relative paths resolve from the temp HTML
# --------------------------------------------------------------------------- #

ATTR_URL = re.compile(
    r'(?P<attr>\b(?:src|href|poster)\s*=\s*)(?P<q>["\'])(?P<url>[^"\']*)(?P=q)',
    re.IGNORECASE,
)
ABSOLUTE_URL = re.compile(r"^(?:[a-z][a-z0-9+.-]*:|//|#|data:|mailto:)", re.IGNORECASE)


def rewrite_urls(html_text: str, base: Path) -> str:
    """Turn document-relative URLs into absolute file:// URLs.

    The rendered HTML lives in a temp directory, so relative references would
    otherwise dangle. Anchors and external schemes are left untouched.
    """
    from urllib.request import url2pathname

    def sub(m):
        url = m.group("url")
        if not url or ABSOLUTE_URL.match(url):
            return m.group(0)
        frag = ""
        if "#" in url:
            url, frag = url.split("#", 1)
            frag = "#" + frag
        if not url:
            return m.group(0)
        try:
            target = (base / url2pathname(url)).resolve()
        except (OSError, ValueError):
            return m.group(0)
        return f'{m.group("attr")}{m.group("q")}{target.as_uri()}{frag}{m.group("q")}'

    return ATTR_URL.sub(sub, html_text)


# --------------------------------------------------------------------------- #
# Stylesheet
# --------------------------------------------------------------------------- #

BASE_CSS = r"""
*, *::before, *::after { box-sizing: border-box; }

/* ---------- Light: neutral slate, quiet rules, roomy ---------- */
:root, :root[data-style="light"] {
  --bg: #fcfcfd; --fg: #1c1e21; --fg-muted: #5c6370; --fg-faint: #8b919c;
  --border: #dfe1e6; --border-soft: #ebedf0; --accent: #3b6fd4;
  --code-bg: #f4f5f7; --quote-border: #cfd4dc; --mark: #fff3bf;
  --bar-bg: rgba(252,252,253,.88); --bar-border: #e3e5ea;
  --btn-hover: rgba(0,0,0,.055); --btn-active: rgba(0,0,0,.11);
  --shadow: 0 1px 2px rgba(0,0,0,.08), 0 10px 30px rgba(0,0,0,.09);
  --canvas: #eef0f4; --menu-bg: #ffffff;
  --side-bg: #f6f7f9; --sel-bg: #e3e9f5;
  --h-rule: transparent; --h-pad: 0;
  --font-sans: "Segoe UI Variable Text", -apple-system, "Segoe UI", system-ui,
               Roboto, "Helvetica Neue", Arial, sans-serif;
  --font-mono: ui-monospace, "Cascadia Mono", Consolas, "Liberation Mono", monospace;
  --body-size: 15.5px; --body-leading: 1.68; --measure: 58rem;
}

/* ---------- Dark ---------- */
:root[data-style="dark"] {
  --bg: #0d1117; --fg: #e6edf3; --fg-muted: #9198a1; --fg-faint: #6e7681;
  --border: #3d444d; --border-soft: #21262d; --accent: #4493f8;
  --code-bg: #161b22; --quote-border: #3d444d; --mark: #4b3d1a;
  --bar-bg: rgba(13,17,23,.88); --bar-border: #30363d;
  --btn-hover: rgba(255,255,255,.08); --btn-active: rgba(255,255,255,.16);
  --shadow: 0 1px 3px rgba(0,0,0,.5), 0 10px 30px rgba(0,0,0,.4);
  --canvas: #010409; --menu-bg: #161b22;
  --side-bg: #0b0f14; --sel-bg: #1f3a5f;
  --h-rule: #21262d; --h-pad: .3em;
  --font-sans: -apple-system, "Segoe UI Variable Text", "Segoe UI", system-ui,
               Roboto, "Helvetica Neue", Arial, sans-serif;
  --font-mono: ui-monospace, "Cascadia Mono", Consolas, "Liberation Mono", monospace;
  --body-size: 15px; --body-leading: 1.6; --measure: 60rem;
}

/* ---------- GitHub: faithful to github.com's rendered markdown ----------
   github-ext shares the palette; it only changes how wide tables may get. */
:root[data-style="github"], :root[data-style="github-ext"] {
  --bg: #ffffff; --fg: #1f2328; --fg-muted: #59636e; --fg-faint: #818b98;
  --border: #d1d9e0; --border-soft: #d1d9e0; --accent: #0969da;
  --code-bg: #f6f8fa; --quote-border: #d1d9e0; --mark: #fff8c5;
  --bar-bg: rgba(255,255,255,.9); --bar-border: #d1d9e0;
  --btn-hover: rgba(0,0,0,.06); --btn-active: rgba(0,0,0,.12);
  --shadow: 0 1px 3px rgba(31,35,40,.12), 0 8px 24px rgba(66,74,83,.12);
  --canvas: #f6f8fa; --menu-bg: #ffffff;
  --side-bg: #f6f8fa; --sel-bg: #ddf4ff;
  --h-rule: #d1d9e0; --h-pad: .3em;
  --font-sans: -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans",
               Helvetica, Arial, sans-serif;
  --font-mono: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas,
               "Liberation Mono", monospace;
  --body-size: 16px; --body-leading: 1.5; --measure: 62rem;
}

/* ---------- typeface ----------
   After the palettes on purpose: these match their specificity, so the later
   rule wins. "system" has no rule at all -- it keeps the style's own stack. */
:root[data-font="sans"] {
  --font-sans: "Segoe UI Variable Text", -apple-system, "Segoe UI", system-ui,
               Roboto, "Helvetica Neue", Arial, sans-serif;
}
:root[data-font="serif"] {
  --font-sans: Georgia, Cambria, "Iowan Old Style", "Palatino Linotype",
               "Times New Roman", serif;
  --body-leading: 1.7;
}
:root[data-font="mono"] { --font-sans: var(--font-mono); --body-size: 14px; }

/* ---------- rainbow columns ---------- */
:root {
  --csv-0: #0b6bcb; --csv-1: #b45309; --csv-2: #15803d; --csv-3: #7c3aed;
  --csv-4: #0e7490; --csv-5: #be123c; --csv-6: #a21caf; --csv-7: #4d7c0f;
  --csv-8: #9a3412; --csv-9: #475569;
}
:root[data-style="dark"] {
  --csv-0: #6cb6ff; --csv-1: #f0b849; --csv-2: #6fdd8b; --csv-3: #c297ff;
  --csv-4: #56d4dd; --csv-5: #ff7b93; --csv-6: #f692ce; --csv-7: #b8e986;
  --csv-8: #ffab70; --csv-9: #9aa8bd;
}

html, body { height: 100%; margin: 0; }
body {
  background: var(--bg); color: var(--fg);
  font: var(--body-size)/var(--body-leading) var(--font-sans);
  -webkit-font-smoothing: antialiased;
  overflow: hidden;
}

/* ---------- toolbar ---------- */
#bar {
  position: fixed; inset: 0 0 auto 0; height: 38px; z-index: 100;
  display: flex; align-items: center; gap: 2px; padding: 0 6px 0 8px;
  background: var(--bar-bg); backdrop-filter: blur(12px) saturate(160%);
  border-bottom: 1px solid var(--bar-border);
  user-select: none; -webkit-user-select: none;
}
#bar .title {
  flex: 1 1 auto; min-width: 0; margin: 0 6px;
  font-size: 12.5px; color: var(--fg-muted);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; direction: rtl;
  text-align: left;
}
#bar .title b { color: var(--fg); font-weight: 600; }
#bar .sep { width: 1px; height: 18px; background: var(--bar-border); margin: 0 4px; }
#bar .dims { color: var(--fg-faint); font-variant-numeric: tabular-nums; }
button.tb {
  appearance: none; border: 0; background: transparent; color: var(--fg-muted);
  height: 26px; min-width: 26px; padding: 0 6px; border-radius: 6px;
  font: inherit; font-size: 13px; cursor: pointer; display: grid; place-items: center;
}
button.tb:hover:not(:disabled) { background: var(--btn-hover); color: var(--fg); }
button.tb:active:not(:disabled) { background: var(--btn-active); }
button.tb:disabled { opacity: .35; cursor: default; }
button.tb svg { width: 15px; height: 15px; fill: none; stroke: currentColor;
                stroke-width: 1.8; stroke-linecap: round; stroke-linejoin: round; }
#zoomLabel {
  min-width: 52px; text-align: center; font-size: 12px; color: var(--fg-muted);
  font-variant-numeric: tabular-nums; cursor: pointer; border-radius: 6px; height: 26px;
  display: grid; place-items: center;
}
#zoomLabel:hover { background: var(--btn-hover); color: var(--fg); }

/* ---------- style menu ---------- */
.menu-wrap { position: relative; display: flex; }
.menu {
  position: absolute; top: 32px; right: 0; z-index: 150; min-width: 176px;
  background: var(--menu-bg); border: 1px solid var(--bar-border);
  border-radius: 10px; box-shadow: var(--shadow); padding: 5px;
  display: flex; flex-direction: column; gap: 1px;
}
.menu[hidden] { display: none; }
.menu .group {
  font-size: 10.5px; text-transform: uppercase; letter-spacing: .06em;
  color: var(--fg-faint); padding: 5px 9px 3px;
}
.menu button {
  appearance: none; border: 0; background: transparent; color: var(--fg);
  font: inherit; font-size: 13px; text-align: left; cursor: pointer;
  padding: 7px 9px; border-radius: 6px;
  display: grid; grid-template-columns: 15px 1fr auto 12px; align-items: center; gap: 8px;
}
.menu button:hover { background: var(--btn-hover); }
.menu button .tick { color: var(--accent); font-size: 12px; visibility: hidden; }
.menu button .tick::after { content: "\2713"; }
.menu button[aria-checked="true"] .tick { visibility: visible; }
.menu button[aria-checked="true"] { font-weight: 600; }
.menu button .key { color: var(--fg-faint); font-size: 11px; }
.menu .swatch {
  width: 15px; height: 15px; border-radius: 4px; border: 1px solid var(--border);
  display: inline-block;
}
.menu .swatch.s-light  { background: linear-gradient(135deg, #fcfcfd 50%, #3b6fd4 50%); }
.menu .swatch.s-dark   { background: linear-gradient(135deg, #0d1117 50%, #4493f8 50%); }
.menu .swatch.s-github { background: linear-gradient(135deg, #ffffff 50%, #0969da 50%); }
.menu .swatch.s-github-ext {
  background: linear-gradient(135deg, #ffffff 50%, #0969da 50%);
  box-shadow: inset 0 0 0 2px #0969da;
}
.menu hr { height: 1px; border: 0; background: var(--bar-border); margin: 4px 2px; }

/* ---------- sidebar ---------- */
:root { --sidebar-w: 264px; --chrome: 72px; }
/* --sidebar-w arrives as an inline style on <body>, which outranks any
   class rule; layout therefore reads --side-offset, which body.no-sidebar
   can override. Declared on body so it picks up body's own --sidebar-w. */
body { --side-offset: var(--sidebar-w); }
body.no-sidebar { --side-offset: 0px; }
body.single-tab { --chrome: 38px; }

#sidebar {
  position: fixed; top: 38px; left: 0; bottom: 0; width: var(--side-offset);
  z-index: 98; display: flex; flex-direction: column;
  background: var(--side-bg); border-right: 1px solid var(--bar-border);
  overflow: hidden; user-select: none; -webkit-user-select: none;
}
body.no-sidebar #sidebar { display: none; }

.pane { display: flex; flex-direction: column; min-height: 0; }
/* --docs-h arrives inline on <body>, like --sidebar-w, so the split persists. */
.pane.docs { flex: 0 0 var(--docs-h, 220px); }
.pane.docs.collapsed { flex: 0 0 auto; }
.pane.files { flex: 1 1 auto; }

/* the draggable separator between the two trees */
#paneGrip {
  flex: none; height: 6px; cursor: row-resize;
  border-top: 1px solid var(--bar-border);
}
#paneGrip:hover, #paneGrip.dragging { background: var(--accent); opacity: .55; }
.pane.docs.collapsed + #paneGrip { cursor: default; }
.pane.docs.collapsed + #paneGrip:hover { background: transparent; opacity: 1; }
.pane > header {
  display: flex; align-items: center; gap: 6px; padding: 7px 10px 6px;
  font-size: 10.5px; text-transform: uppercase; letter-spacing: .07em;
  color: var(--fg-faint); font-weight: 600; flex: none; cursor: pointer;
}
.pane > header:hover { color: var(--fg-muted); }
.pane > header .caret { transition: transform .12s ease; font-size: 9px; }
.pane.collapsed > header .caret { transform: rotate(-90deg); }
.pane.collapsed { flex: 0 0 auto; max-height: none; }
.pane.collapsed .tree { display: none; }
.pane > header .count { margin-left: auto; font-weight: 400; letter-spacing: 0; }
.pane > header .reveal {
  margin-left: auto; appearance: none; border: 0; background: transparent;
  color: var(--fg-faint); cursor: pointer; font-size: 12px; line-height: 1;
  padding: 2px 4px; border-radius: 4px;
}
.pane > header .reveal:hover { background: var(--btn-hover); color: var(--fg); }
.tree {
  flex: 1 1 auto; min-height: 0; overflow: auto; padding: 0 0 8px;
  scrollbar-width: thin; scrollbar-color: var(--fg-faint) transparent;
}
.tree::-webkit-scrollbar { width: 10px; }
.tree::-webkit-scrollbar-thumb {
  background: var(--fg-faint); border-radius: 8px;
  border: 3px solid var(--side-bg); background-clip: padding-box;
}
.tree .empty { padding: 4px 12px 8px; color: var(--fg-faint); font-size: 12px; }

.row {
  display: flex; align-items: center; gap: 4px; padding: 2px 8px 2px 0;
  font-size: 12.5px; line-height: 1.5; color: var(--fg-muted);
  white-space: nowrap; cursor: default; border-radius: 4px;
}
.row:hover { background: var(--btn-hover); color: var(--fg); }
.row.file { cursor: pointer; }
.row.active { background: var(--sel-bg); color: var(--fg); font-weight: 600; }
.row .chev {
  flex: none; width: 14px; text-align: center; font-size: 9px;
  color: var(--fg-faint); transition: transform .12s ease;
}
.row .chev.spin { animation: mdvspin .7s linear infinite; }
@keyframes mdvspin { to { transform: rotate(360deg); } }
.node.open > .row > .chev { transform: rotate(90deg); }
.row .chev.leaf { visibility: hidden; }
.row .ico { flex: none; width: 14px; text-align: center; opacity: .75; font-size: 11px; }
.row .nm { overflow: hidden; text-overflow: ellipsis; }
.row .dot {
  flex: none; width: 6px; height: 6px; border-radius: 50%;
  background: var(--accent); margin-left: 4px; visibility: hidden;
}
.row.stale .dot { visibility: visible; }
.row .x {
  flex: none; appearance: none; border: 0; background: transparent; color: inherit;
  width: 17px; height: 17px; margin-left: auto; border-radius: 4px; cursor: pointer;
  font: inherit; font-size: 13px; line-height: 1; display: grid; place-items: center;
  opacity: 0;
}
.row:hover .x, .row.active .x { opacity: .55; }
.row .x:hover { background: var(--btn-active); opacity: 1; }
.node > .kids { display: none; }
.node.open > .kids { display: block; }
.row.more { color: var(--fg-faint); font-style: italic; cursor: default; }
.row.denied { color: var(--fg-faint); font-style: italic; }

#sideResize {
  position: fixed; top: 38px; bottom: 0; width: 5px; z-index: 101;
  left: calc(var(--side-offset) - 2px); cursor: col-resize;
}
#sideResize:hover, #sideResize.dragging { background: var(--accent); opacity: .55; }
body.no-sidebar #sideResize { display: none; }

/* ---------- tab strip ---------- */
#tabs {
  position: fixed; top: 38px; left: var(--side-offset); right: 0; height: 34px; z-index: 99;
  display: flex; align-items: stretch; gap: 2px; padding: 0 6px;
  background: var(--bar-bg); backdrop-filter: blur(12px) saturate(160%);
  border-bottom: 1px solid var(--bar-border);
  overflow-x: auto; overflow-y: hidden;
  scrollbar-width: none; user-select: none; -webkit-user-select: none;
}
#tabs::-webkit-scrollbar { height: 0; }
body.single-tab #tabs { display: none; }
.tab {
  display: flex; align-items: center; gap: 6px; flex: 0 1 auto;
  min-width: 0; max-width: 240px; padding: 0 6px 0 10px; margin: 4px 0 0;
  border: 1px solid transparent; border-bottom: 0;
  border-radius: 8px 8px 0 0; cursor: default;
  font-size: 12.5px; color: var(--fg-muted); background: transparent;
}
.tab:hover { background: var(--btn-hover); }
.tab[aria-selected="true"] {
  background: var(--bg); border-color: var(--bar-border);
  color: var(--fg); font-weight: 600;
}
.tab .label { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.tab .dot {
  width: 6px; height: 6px; border-radius: 50%; background: var(--accent);
  flex: none; visibility: hidden;
}
.tab[data-stale="1"] .dot { visibility: visible; }
.tab .x {
  appearance: none; border: 0; background: transparent; color: inherit;
  width: 18px; height: 18px; flex: none; border-radius: 4px; cursor: pointer;
  font: inherit; font-size: 14px; line-height: 1; display: grid; place-items: center;
  opacity: .5;
}
.tab .x:hover { background: var(--btn-active); opacity: 1; }
#newTab {
  appearance: none; border: 0; background: transparent; color: var(--fg-muted);
  width: 26px; margin: 4px 0 0; border-radius: 6px; cursor: pointer;
  font: inherit; font-size: 16px; flex: none;
}
#newTab:hover { background: var(--btn-hover); color: var(--fg); }

/* ---------- scroll host ---------- */
#scroller {
  position: absolute; inset: var(--chrome) 0 0 var(--side-offset); overflow: auto;
  scrollbar-color: var(--fg-faint) transparent;
}
#scroller::-webkit-scrollbar { width: 12px; height: 12px; }
#scroller::-webkit-scrollbar-thumb {
  background: var(--fg-faint); border-radius: 8px;
  border: 3px solid var(--bg); background-clip: padding-box;
}
#scroller::-webkit-scrollbar-thumb:hover { background: var(--fg-muted); background-clip: padding-box; }

/* ---------- document ---------- */
#content { zoom: 1; }
body.mode-doc #content { max-width: var(--measure); margin: 0 auto; padding: 30px 40px 60vh; }
body.mode-doc.wide #content { max-width: none; }

/* ---------- github-ext: text keeps its measure, tables do not ----------
   The column itself goes full width; every block is held back to the usual
   measure and centred, so text reads exactly as before. Top-level tables are
   exempt: they take the width they need, up to the whole window, and centre
   on the column. A table narrower than the column still lines up with the
   text, because min-width keeps its box as wide as the column. */
:root[data-style="github-ext"] body.mode-doc:not(.is-csv) #content {
  --column: min(100%, calc(var(--measure) - 80px));
  max-width: none;
}
:root[data-style="github-ext"] body.mode-doc:not(.is-csv) #content > * {
  max-width: var(--column);
  margin-left: auto; margin-right: auto;
}
:root[data-style="github-ext"] body.mode-doc:not(.is-csv) #content > table {
  width: max-content; min-width: var(--column); max-width: 100%;
}
:root[data-style="github-ext"] body.mode-doc.wide #content > * { max-width: none; }

/* github-ext zoom magnifies instead of reflowing. The page is laid out at the
   window's width as it is at 100% (--view-w, kept current by the viewer
   script, in unzoomed pixels) and the zoom then scales that layout as a
   whole, so zooming in makes the document bigger than the window and it is
   explored by dragging, like an image. Elsewhere zoom reflows the text. */
:root[data-style="github-ext"] body.mode-doc #scroller { scrollbar-gutter: stable; }
:root[data-style="github-ext"] body.mode-doc #content { width: var(--view-w, auto); }

/* SVG in a document: a picture standing on its own line -- an image or inline
   markup -- leaves the text column and is drawn across the whole window. It
   is vector, so it stays sharp at that size and at any zoom. */
:root[data-style="github-ext"] body.mode-doc #content > p:has(> img[src*=".svg" i]:only-child),
:root[data-style="github-ext"] body.mode-doc #content > p:has(> svg[viewBox]:only-child) {
  max-width: 100%;
}
:root[data-style="github-ext"] body.mode-doc #content > p > img[src*=".svg" i]:only-child,
:root[data-style="github-ext"] body.mode-doc #content > p > svg[viewBox]:only-child,
:root[data-style="github-ext"] body.mode-doc #content > svg[viewBox] {
  display: block; width: 100%; height: auto; max-width: none;
}

#content > :first-child { margin-top: 0; }
h1, h2, h3, h4, h5, h6 { margin: 1.6em 0 .6em; line-height: 1.28; font-weight: 600; }
h1 { font-size: 1.9em; padding-bottom: var(--h-pad); border-bottom: 1px solid var(--h-rule); }
h2 { font-size: 1.45em; padding-bottom: var(--h-pad); border-bottom: 1px solid var(--h-rule); }
h3 { font-size: 1.2em; } h4 { font-size: 1em; }
h5 { font-size: .9em; } h6 { font-size: .85em; color: var(--fg-muted); }
p, ul, ol, dl, table, pre, blockquote, .mermaid-figure { margin: 0 0 1em; }
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }
a.headerlink { visibility: hidden; margin-left: .35em; color: var(--fg-faint); font-weight: 400; }
a.headerlink::after { content: "#"; }
h1:hover a.headerlink, h2:hover a.headerlink, h3:hover a.headerlink,
h4:hover a.headerlink, h5:hover a.headerlink, h6:hover a.headerlink { visibility: visible; }
ul, ol { padding-left: 1.8em; }
li { margin: .25em 0; }
li > ul, li > ol { margin: .25em 0; }
li.task-item { list-style: none; margin-left: -1.4em; }
li.task-item input { margin-right: .5em; vertical-align: middle; }
hr { height: 1px; border: 0; background: var(--border); margin: 2em 0; }
blockquote {
  padding: 0 1em; color: var(--fg-muted);
  border-left: .25em solid var(--quote-border);
}
blockquote > :last-child { margin-bottom: 0; }
img, video { max-width: 100%; height: auto; border-radius: 4px; }
mark { background: var(--mark); color: inherit; }
kbd {
  font: 11px/1 var(--font-mono); padding: 3px 5px;
  border: 1px solid var(--border); border-bottom-width: 2px;
  border-radius: 4px; background: var(--code-bg);
}
code, kbd, pre, samp { font-family: var(--font-mono); }
code { font-size: .875em; background: var(--code-bg); padding: .2em .4em; border-radius: 4px; }
pre { background: var(--code-bg); padding: 14px 16px; border-radius: 8px;
      overflow: auto; line-height: 1.45; font-size: .875em; }
pre code { background: none; padding: 0; font-size: 1em; }
.codehilite { background: var(--code-bg); border-radius: 8px; overflow: auto; }
.codehilite pre { margin: 0; background: none; }
table { border-collapse: collapse; display: block; overflow-x: auto; max-width: 100%; }
th, td { padding: 6px 13px; border: 1px solid var(--border); }
th { background: var(--code-bg); font-weight: 600; text-align: left; }
tr:nth-child(2n) td { background: color-mix(in srgb, var(--code-bg) 55%, transparent); }
dt { font-weight: 600; margin-top: .8em; }
dd { margin: 0 0 0 1.6em; color: var(--fg-muted); }
sup a, .footnote { font-size: .85em; }
.footnote { border-top: 1px solid var(--border-soft); margin-top: 3em; color: var(--fg-muted); }
.admonition {
  border: 1px solid var(--border); border-left: 4px solid var(--accent);
  border-radius: 6px; padding: 10px 16px; margin: 0 0 1em; background: var(--code-bg);
}
.admonition-title { font-weight: 600; margin: 0 0 .4em; }
.admonition > :last-child { margin-bottom: 0; }
.admonition.warning { border-left-color: #d29922; }
.admonition.danger, .admonition.error { border-left-color: #cf222e; }
.admonition.tip, .admonition.hint { border-left-color: #1a7f37; }

/* ---------- mermaid ---------- */
.mermaid-figure {
  display: flex; justify-content: center; padding: 8px 0;
  background: transparent; overflow-x: auto;
}
pre.mermaid { background: none; padding: 0; margin: 0; overflow: visible; text-align: center; }
pre.mermaid:not([data-processed]) { color: var(--fg-faint); font-size: .8em; text-align: left; }
pre.mermaid svg { max-width: 100%; height: auto; }
body.mode-mermaid #content {
  min-height: calc(100vh - var(--chrome)); display: grid; place-items: center;
  padding: 24px;
}
body.mode-mermaid .mermaid-figure { margin: 0; }
body.mode-mermaid pre.mermaid svg { max-width: none; }

/* github-ext: a diagram gets the whole window, not the text column.
   The figure is a full-width block rather than a shrink-to-fit flex item:
   mermaid sizes a gantt chart to its container, so a shrunken container drew
   it a couple of hundred pixels wide. Other diagrams keep their natural size
   and scroll only when they are wider than the window. */
:root[data-style="github-ext"] body.mode-doc:not(.is-csv) #content > .mermaid-figure {
  max-width: 100%;
}
:root[data-style="github-ext"] .mermaid-figure { display: block; min-width: 0; }
:root[data-style="github-ext"] pre.mermaid { width: 100%; }
:root[data-style="github-ext"] pre.mermaid svg { max-width: none; overflow: visible; }
:root[data-style="github-ext"] body.mode-mermaid #content { justify-items: stretch; }

/* ---------- image canvas ---------- */
body.mode-image { background: var(--canvas); }
body.mode-image #scroller {
  background: var(--canvas);
  display: grid; place-items: center;
  cursor: grab;
}
body.mode-image #scroller.panning { cursor: grabbing; }

/* Documents and diagrams pan by dragging anywhere that is not text: the
   margins and the diagrams show a hand, text keeps its I-beam for selecting. */
body.mode-doc #scroller, body.mode-mermaid #scroller { cursor: grab; }
body.mode-doc #content *, body.mode-mermaid #content * { cursor: auto; }
#content pre.mermaid svg, #content pre.mermaid svg *,
#content img, #content p > svg, #content p > svg *, #content > svg, #content > svg * {
  cursor: grab;
}
body.dragging, body.dragging * { cursor: grabbing !important; user-select: none; }
body.mode-image #scroller.fits { overflow: hidden; }
#imgview {
  display: block; border-radius: 0; max-width: none;
  image-rendering: auto; -webkit-user-drag: none; user-select: none;
}
#imgview.checker {
  background-image:
    linear-gradient(45deg, rgba(128,128,128,.18) 25%, transparent 25% 75%, rgba(128,128,128,.18) 75%),
    linear-gradient(45deg, rgba(128,128,128,.18) 25%, transparent 25% 75%, rgba(128,128,128,.18) 75%);
  background-size: 20px 20px; background-position: 0 0, 10px 10px;
}

/* ---------- delimited files ---------- */
body.is-csv #content { max-width: none; padding: 18px 22px 40vh; }
.csv-info {
  color: var(--fg-muted); font-size: 12px; margin: 0 0 10px;
  font-family: var(--font-sans);
}
.csv-info code {
  background: var(--code-bg); padding: 1px 5px; border-radius: 4px; font-size: 11px;
}
.csv-cut { margin: 10px 0 0; font-style: italic; }
pre.csv {
  background: var(--code-bg); border: 1px solid var(--border-soft);
  border-radius: 8px; padding: 10px 12px; margin: 0;
  overflow: auto; white-space: pre; font-size: .84em; line-height: 1.55;
  tab-size: 4;
}
.csv-row { white-space: pre; }
.csv-row:hover { background: var(--btn-hover); }
.csv-head { font-weight: 700; }
.csv-d { color: var(--fg-faint); }
.c0 { color: var(--csv-0); } .c1 { color: var(--csv-1); }
.c2 { color: var(--csv-2); } .c3 { color: var(--csv-3); }
.c4 { color: var(--csv-4); } .c5 { color: var(--csv-5); }
.c6 { color: var(--csv-6); } .c7 { color: var(--csv-7); }
.c8 { color: var(--csv-8); } .c9 { color: var(--csv-9); }

#alignBtn { display: none; }
body.is-csv #alignBtn { display: grid; }
#alignBtn[aria-pressed="true"] { background: var(--btn-active); color: var(--accent); }

/* ---------- find bar ---------- */
#findbar {
  position: fixed; top: calc(var(--chrome) + 10px); right: 20px; z-index: 140;
  display: flex; align-items: center; gap: 2px;
  background: var(--menu-bg); border: 1px solid var(--bar-border);
  border-radius: 10px; box-shadow: var(--shadow); padding: 5px 6px 5px 10px;
}
#findbar[hidden] { display: none; }
#findInput {
  appearance: none; border: 0; background: transparent; color: var(--fg);
  font: inherit; font-size: 13px; width: 200px; padding: 3px 0; outline: none;
}
#findInput::placeholder { color: var(--fg-faint); }
#findCount {
  font-size: 11.5px; color: var(--fg-muted); font-variant-numeric: tabular-nums;
  min-width: 56px; text-align: right; padding: 0 8px 0 4px; white-space: nowrap;
}
#findbar.none #findCount { color: #cf222e; }
#findbar .sep { width: 1px; height: 16px; background: var(--bar-border); margin: 0 3px; }
#findbar button {
  appearance: none; border: 0; background: transparent; color: var(--fg-muted);
  width: 24px; height: 24px; border-radius: 6px; cursor: pointer;
  display: grid; place-items: center; font: inherit; font-size: 14px; line-height: 1;
}
#findbar button:hover:not(:disabled) { background: var(--btn-hover); color: var(--fg); }
#findbar button:disabled { opacity: .3; cursor: default; }
#findbar button svg {
  width: 13px; height: 13px; fill: none; stroke: currentColor;
  stroke-width: 2; stroke-linecap: round; stroke-linejoin: round;
}
body.mode-image #findBtn, body.mode-blank #findBtn { display: none; }

/* Painted through the Custom Highlight API, so the document itself is never
   rewritten -- mermaid diagrams, highlighted code and csv colours stay put. */
::highlight(mdv-find) { background: #fff2a8; color: #1c1e21; }
::highlight(mdv-find-current) { background: #ff9a3c; color: #1c1e21; }
:root[data-style="dark"] ::highlight(mdv-find) { background: #4a4327; color: #ffffff; }
:root[data-style="dark"] ::highlight(mdv-find-current) { background: #b7791f; color: #ffffff; }

/* ---------- welcome / error ---------- */
.mdv-center {
  position: absolute; inset: 0; display: grid; place-items: center; text-align: center;
  padding: 24px;
}
.mdv-center .inner { max-width: 32rem; }
.mdv-center h1 { border: 0; font-size: 1.35em; margin: 0 0 .4em; }
.mdv-center p { color: var(--fg-muted); }
.mdv-center .glyph { font-size: 44px; line-height: 1; opacity: .35; margin-bottom: .5em; }
.mdv-center button {
  appearance: none; margin-top: 1.2em; padding: 8px 18px; font: inherit; font-size: 14px;
  border: 1px solid var(--border); border-radius: 8px; background: var(--code-bg);
  color: var(--fg); cursor: pointer;
}
.mdv-center button:hover { border-color: var(--accent); color: var(--accent); }
.mdv-error { padding: 30px 40px; }
.mdv-error h1 { color: #cf222e; border: 0; }
kbd.hint { margin: 0 2px; }
.shortcuts { margin-top: 2em; font-size: 12px; color: var(--fg-faint); line-height: 2; }

/* ---------- transient zoom toast ---------- */
#toast {
  position: fixed; bottom: 20px; left: 50%; transform: translateX(-50%);
  background: var(--bar-bg); backdrop-filter: blur(12px); box-shadow: var(--shadow);
  border: 1px solid var(--bar-border); border-radius: 999px;
  padding: 6px 16px; font-size: 12.5px; font-variant-numeric: tabular-nums;
  opacity: 0; transition: opacity .18s ease; pointer-events: none; z-index: 200;
}
#toast.show { opacity: 1; }

@media print {
  #bar, #toast { display: none; }
  #scroller { position: static; overflow: visible; inset: auto; }
  body { overflow: visible; }
}
"""


@functools.cache
def pygments_css() -> str:
    """Syntax-highlighting rules for every style, each scoped by data-style.

    All three sets ship in the page, so switching style is instant and needs no
    re-render. The result never changes, so it is built once per process
    rather than on every navigation.
    """
    try:
        from pygments.formatters import HtmlFormatter
        from pygments.styles import get_all_styles
    except ImportError:
        return ""

    available = set(get_all_styles())
    out = []
    for style in STYLES:
        name = next((n for n in STYLE_PYGMENTS[style] if n in available), "default")
        formatter = HtmlFormatter(style=name)
        selector = f':root[data-style="{style}"] .codehilite'
        if style == "light":  # also the default when no attribute is set yet
            selector += f", :root:not([data-style]) .codehilite"
        out.append(formatter.get_style_defs(selector))
    return "\n".join(out)


# --------------------------------------------------------------------------- #
# Viewer JavaScript
# --------------------------------------------------------------------------- #

VIEWER_JS = r"""
(function () {
  "use strict";
  var CFG = window.__MDV__;
  var bridgeKey = (function () {
    var hash = window.location.hash;
    if (!/^#[A-Za-z0-9_-]{43}$/.test(hash)) return "";
    // Keep the key in this page's closure, out of the browser history URL.
    try { window.history.replaceState(null, "", window.location.href.split("#")[0]); }
    catch (err) { return ""; }
    return hash.slice(1);
  })();
  var STEPS = CFG.steps;
  var scroller = document.getElementById("scroller");
  var content  = document.getElementById("content");
  var img      = document.getElementById("imgview");
  var label    = document.getElementById("zoomLabel");
  var toastEl  = document.getElementById("toast");
  var mode     = CFG.mode;                 // doc | mermaid | image | blank
  var zoom     = CFG.zoom || 1;
  var fitMode  = mode === "image" && CFG.fit !== false;
  var natural  = { w: 0, h: 0 };
  var toastTimer = null;

  /* ------------------------------------------------------------------ */
  /* zoom                                                               */
  /* ------------------------------------------------------------------ */

  function clamp(z) { return Math.min(STEPS[STEPS.length - 1], Math.max(STEPS[0], z)); }

  function nearestStep(z, dir) {
    if (dir > 0) {
      for (var i = 0; i < STEPS.length; i++) if (STEPS[i] > z + 1e-4) return STEPS[i];
      return STEPS[STEPS.length - 1];
    }
    for (var j = STEPS.length - 1; j >= 0; j--) if (STEPS[j] < z - 1e-4) return STEPS[j];
    return STEPS[0];
  }

  function fitZoom() {
    if (!natural.w || !natural.h) return 1;
    var pad = 32;
    var sx = (scroller.clientWidth - pad) / natural.w;
    var sy = (scroller.clientHeight - pad) / natural.h;
    var z = Math.min(sx, sy);
    if (!CFG.vector) z = Math.min(1, z);     // never upscale raster art in fit mode
    return clamp(z > 0 ? z : 1);
  }

  function render(anchor) {
    if (mode === "image") {
      if (!natural.w) return;
      var before = anchor || {
        x: scroller.clientWidth / 2, y: scroller.clientHeight / 2,
        rx: (scroller.scrollLeft + scroller.clientWidth / 2) / Math.max(1, img.offsetWidth),
        ry: (scroller.scrollTop + scroller.clientHeight / 2) / Math.max(1, img.offsetHeight)
      };
      img.style.width = Math.round(natural.w * zoom) + "px";
      img.style.height = Math.round(natural.h * zoom) + "px";
      var fits = img.offsetWidth <= scroller.clientWidth &&
                 img.offsetHeight <= scroller.clientHeight;
      scroller.classList.toggle("fits", fits);
      if (!fits) {
        scroller.scrollLeft = before.rx * img.offsetWidth - before.x;
        scroller.scrollTop  = before.ry * img.offsetHeight - before.y;
      }
    } else {
      // Keep whatever sits under the anchor (the pointer, or the middle of the
      // view) where it is. Not on the first paint: the saved scroll position
      // is restored after that.
      var previous = parseFloat(content.style.zoom || "0");
      var keep = previous && previous !== zoom
        ? holdPoint(anchor || { x: scroller.clientWidth / 2, y: scroller.clientHeight / 2 })
        : null;
      content.style.zoom = zoom;
      if (keep) keep();
    }
    updateLabel();
  }

  /* The element that scrolls sideways for `el`: a wide diagram, table or code
     block scrolls inside its own box; everything else scrolls the page. */
  function scrollBoxX(el) {
    for (var node = el; node && node !== scroller; node = node.parentElement) {
      if (node.scrollWidth > node.clientWidth + 1) {
        var ox = getComputedStyle(node).overflowX;
        if (ox === "auto" || ox === "scroll") return node;
      }
    }
    return scroller;
  }

  /* Remember the element under a point (scroller coordinates) and where in it
     the point falls; the returned function scrolls it back under the point.
     An element rather than a page fraction, because text reflows as it
     zooms and the page height changes unevenly. */
  function holdPoint(a) {
    var sr = scroller.getBoundingClientRect();
    var x = sr.left + a.x, y = sr.top + a.y;
    var el = document.elementFromPoint(x, y);
    if (!el || !content.contains(el)) el = content;
    var r = el.getBoundingClientRect();
    var fx = (x - r.left) / Math.max(1, r.width);
    var fy = (y - r.top) / Math.max(1, r.height);
    return function () {
      var n = el.getBoundingClientRect();
      var dx = n.left + fx * n.width - x, dy = n.top + fy * n.height - y;
      var box = scrollBoxX(el), before = box.scrollLeft;
      box.scrollLeft += dx;
      if (box !== scroller) scroller.scrollLeft += dx - (box.scrollLeft - before);
      scroller.scrollTop += dy;
    };
  }

  function updateLabel() {
    var pct = Math.round(zoom * 100);
    label.textContent = (fitMode ? "Fit" : pct + "%");
    label.title = pct + "% - click to reset to 100%";
    var minus = document.getElementById("zoomOut"), plus = document.getElementById("zoomIn");
    if (minus) minus.disabled = zoom <= STEPS[0] + 1e-4;
    if (plus) plus.disabled = zoom >= STEPS[STEPS.length - 1] - 1e-4;
  }

  function toast(text) {
    if (!toastEl) return;
    toastEl.textContent = text;
    toastEl.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { toastEl.classList.remove("show"); }, 900);
  }

  function setZoom(z, opts) {
    opts = opts || {};
    fitMode = false;
    zoom = clamp(z);
    render(opts.anchor);
    if (!opts.silent) toast(Math.round(zoom * 100) + "%");
    persist();
  }

  function step(dir, anchor) { setZoom(nearestStep(zoom, dir), { anchor: anchor }); }

  function doFit() {
    if (mode !== "image") { setZoom(1); return; }
    fitMode = true;
    zoom = fitZoom();
    render();
    toast("Fit");
    persist();
  }

  function resetZoom() { setZoom(1); }

  var persistTimer = null;
  function persist() {
    clearTimeout(persistTimer);
    persistTimer = setTimeout(function () {
      call("save_view_prefs", {
        zoom: zoom, style: document.documentElement.dataset.style,
        fit: fitMode, mode: mode
      });
    }, 400);
  }

  /* ------------------------------------------------------------------ */
  /* image setup + panning                                              */
  /* ------------------------------------------------------------------ */

  if (mode === "image" && img) {
    var ready = function () {
      // CFG.viewBox is set only when the file itself declares no absolute size,
      // in which case the engine's naturalWidth is a placeholder (see
      // svg_dimensions in md-view.py).
      if (CFG.viewBox) {
        natural.w = CFG.viewBox[0];
        natural.h = CFG.viewBox[1];
      } else {
        natural.w = img.naturalWidth || 800;
        natural.h = img.naturalHeight || 600;
      }
      img.dataset.naturalWidth = natural.w;
      img.dataset.naturalHeight = natural.h;
      if (fitMode) { zoom = fitZoom(); }
      render();
      var d = document.getElementById("dims");
      if (d) d.textContent = Math.round(natural.w) + " × " + Math.round(natural.h);
    };
    if (img.complete && img.naturalWidth) ready(); else img.addEventListener("load", ready);
    img.addEventListener("error", function () {
      document.getElementById("scroller").innerHTML =
        '<div class="mdv-center"><div class="inner"><div class="glyph">&#9888;</div>' +
        "<h1>Cannot display this image</h1><p>The file may be corrupt or in an " +
        "unsupported format.</p></div></div>";
    });

    var pan = null;
    scroller.addEventListener("pointerdown", function (e) {
      if (e.button !== 0 || scroller.classList.contains("fits")) return;
      pan = { x: e.clientX, y: e.clientY, sl: scroller.scrollLeft, st: scroller.scrollTop };
      scroller.classList.add("panning");
      scroller.setPointerCapture(e.pointerId);
    });
    scroller.addEventListener("pointermove", function (e) {
      if (!pan) return;
      scroller.scrollLeft = pan.sl - (e.clientX - pan.x);
      scroller.scrollTop  = pan.st - (e.clientY - pan.y);
    });
    var endPan = function () { pan = null; scroller.classList.remove("panning"); };
    scroller.addEventListener("pointerup", endPan);
    scroller.addEventListener("pointercancel", endPan);
    scroller.addEventListener("dblclick", function () {
      if (fitMode) setZoom(1); else doFit();
    });
    window.addEventListener("resize", function () { if (fitMode) { zoom = fitZoom(); render(); } });
  }

  /* ------------------------------------------------------------------ */
  /* the unzoomed page width, for github-ext's magnifying zoom          */
  /* ------------------------------------------------------------------ */

  /* The scroller is not zoomed, so its width is the window's width at 100%.
     #content takes it as its own width in github-ext (see the stylesheet). */
  function updateViewWidth() {
    content.style.setProperty("--view-w", scroller.clientWidth + "px");
  }
  if (content && scroller) {
    updateViewWidth();
    if (window.ResizeObserver) new ResizeObserver(updateViewWidth).observe(scroller);
    else window.addEventListener("resize", updateViewWidth);
  }

  /* ------------------------------------------------------------------ */
  /* drag to pan documents and diagrams                                 */
  /* ------------------------------------------------------------------ */

  /* True when (x, y) is over an actual character, so a drag there should
     select text rather than pan. Whitespace beside or between blocks pans. */
  function overText(x, y) {
    if (!document.caretRangeFromPoint) return false;
    var hit = document.caretRangeFromPoint(x, y);
    if (!hit || hit.startContainer.nodeType !== 3) return false;
    var node = hit.startContainer, probe = document.createRange();
    var from = Math.max(0, hit.startOffset - 1);
    var to = Math.min(node.length - 1, hit.startOffset);
    for (var i = from; i <= to; i++) {
      probe.setStart(node, i); probe.setEnd(node, i + 1);
      var rects = probe.getClientRects();
      for (var j = 0; j < rects.length; j++) {
        var b = rects[j];
        if (x >= b.left - 1 && x <= b.right + 1 && y >= b.top - 1 && y <= b.bottom + 1) {
          return true;
        }
      }
    }
    return false;
  }

  function canPan(e) {
    var t = e.target;
    if (!t || !t.closest || t.closest("a, button, input, textarea, select, summary, label")) {
      return false;
    }
    // A press on a scrollbar belongs to the scrollbar. Measured on screen:
    // inside zoomed content, client sizes are unzoomed but the pointer is not.
    if (t.clientWidth && (t.offsetWidth > t.clientWidth + t.clientLeft
                          || t.offsetHeight > t.clientHeight + t.clientTop)) {
      var box = t.getBoundingClientRect(), scale = box.width / Math.max(1, t.offsetWidth);
      if (e.clientX - box.left > (t.clientLeft + t.clientWidth) * scale ||
          e.clientY - box.top > (t.clientTop + t.clientHeight) * scale) return false;
    }
    if (t.closest("pre.mermaid svg, svg, img")) return true;  // pictures always pan
    return mode === "mermaid" || !overText(e.clientX, e.clientY);
  }

  if (mode === "doc" || mode === "mermaid") {
    var drag = null, swallowClick = false;
    scroller.addEventListener("mousedown", function (e) {
      swallowClick = false;            // a new press starts a new gesture
      if (e.button !== 0 || e.detail > 1 || !canPan(e)) return;
      e.preventDefault();              // no text selection, no native svg drag
      drag = { x: e.clientX, y: e.clientY, moved: false,
               box: scrollBoxX(e.target), sl: 0, st: scroller.scrollTop };
      drag.sl = drag.box.scrollLeft;
      drag.pageSl = scroller.scrollLeft;
    });
    window.addEventListener("mousemove", function (e) {
      if (!drag) return;
      var dx = e.clientX - drag.x, dy = e.clientY - drag.y;
      if (!drag.moved) {
        if (Math.abs(dx) < 4 && Math.abs(dy) < 4) return;   // still a click
        drag.moved = true;
        document.body.classList.add("dragging");
      }
      drag.box.scrollLeft = drag.sl - dx;
      if (drag.box !== scroller) scroller.scrollLeft = drag.pageSl - dx;
      scroller.scrollTop = drag.st - dy;
    });
    window.addEventListener("mouseup", function () {
      if (!drag) return;
      if (drag.moved) {
        swallowClick = true;           // a pan is not a click on what lies below
        setTimeout(function () { swallowClick = false; }, 0);
      } else {
        // A plain click on blank space clears a selection, as it normally would.
        var sel = window.getSelection();
        if (sel && !sel.isCollapsed) sel.removeAllRanges();
      }
      drag = null;
      document.body.classList.remove("dragging");
    });
    scroller.addEventListener("click", function (e) {
      if (swallowClick) { e.preventDefault(); e.stopPropagation(); swallowClick = false; }
    }, true);
  }

  /* ------------------------------------------------------------------ */
  /* wheel + keyboard                                                   */
  /* ------------------------------------------------------------------ */

  scroller.addEventListener("wheel", function (e) {
    if (!e.ctrlKey && !e.metaKey) return;
    e.preventDefault();
    var r = scroller.getBoundingClientRect();
    var anchor = null;
    if (mode === "image" && img && img.offsetWidth) {
      anchor = {
        x: e.clientX - r.left, y: e.clientY - r.top,
        rx: (scroller.scrollLeft + e.clientX - r.left) / img.offsetWidth,
        ry: (scroller.scrollTop + e.clientY - r.top) / img.offsetHeight
      };
    } else if (mode !== "image") {
      anchor = { x: e.clientX - r.left, y: e.clientY - r.top };   // zoom about the pointer
    }
    var factor = Math.exp(-e.deltaY * 0.0016);
    setZoom(zoom * factor, { anchor: anchor });
  }, { passive: false });

  document.addEventListener("keydown", function (e) {
    var ctrl = e.ctrlKey || e.metaKey;
    var target = e.target;
    var typing = !!target && (target.tagName === "INPUT"
                              || target.tagName === "TEXTAREA"
                              || target.isContentEditable);
    if (ctrl && e.key.toLowerCase() === "f") { e.preventDefault(); openFind(); return; }
    if (e.key === "F3") { e.preventDefault(); stepFind(e.shiftKey ? -1 : 1); return; }
    if (ctrl && (e.key === "+" || e.key === "=" || e.code === "NumpadAdd")) {
      e.preventDefault(); step(+1); return;
    }
    if (ctrl && (e.key === "-" || e.key === "_" || e.code === "NumpadSubtract")) {
      e.preventDefault(); step(-1); return;
    }
    if (ctrl && (e.key === "0" || e.code === "Numpad0")) { e.preventDefault(); resetZoom(); return; }
    if (ctrl && e.key.toLowerCase() === "o") { e.preventDefault(); call("pick_file"); return; }
    if (ctrl && e.key.toLowerCase() === "d") { e.preventDefault(); cycleStyle(); return; }
    if (ctrl && e.key.toLowerCase() === "b") { e.preventDefault(); toggleSidebar(); return; }
    if (ctrl && e.key.toLowerCase() === "t") { e.preventDefault(); call("new_tab"); return; }
    if (ctrl && e.key.toLowerCase() === "w") { e.preventDefault(); call("close_tab", -1); return; }
    if (ctrl && e.key === "Tab") {
      e.preventDefault();
      call(e.shiftKey ? "prev_tab" : "next_tab");
      return;
    }
    if (ctrl && e.key >= "1" && e.key <= "9") {
      e.preventDefault(); call("select_tab", parseInt(e.key, 10) - 1); return;
    }
    if (e.key === "F5" || (ctrl && e.key.toLowerCase() === "r")) {
      e.preventDefault(); call("refresh"); return;
    }
    if (e.key === "F11") { e.preventDefault(); call("toggle_fullscreen"); return; }
    if (e.key === "Escape") {
      if (anyMenuOpen()) { closeMenus(null); return; }
      if (findOpen()) { closeFind(); return; }
      call("escape"); return;
    }
    if (!ctrl && !e.altKey && !typing) {
      if (e.key === "f") { e.preventDefault(); doFit(); return; }
      // 1-4 pick a style directly; they also label the menu rows.
      if (e.key >= "1" && e.key <= String(STYLES.length)) {
        e.preventDefault();
        var picked = STYLES[parseInt(e.key, 10) - 1];
        applyStyle(picked);
        toast(picked.charAt(0).toUpperCase() + picked.slice(1));
        return;
      }
      if (e.key === "0") { e.preventDefault(); setZoom(1); return; }
      if (e.key === "+" || e.key === "=") { e.preventDefault(); step(+1); return; }
      if (e.key === "-") { e.preventDefault(); step(-1); return; }
      if (e.key === "[" || (e.key === "ArrowLeft" && e.altKey)) { e.preventDefault(); call("go_back"); return; }
      if (e.key === "]") { e.preventDefault(); call("go_forward"); return; }
      if (e.key === "w" && mode === "doc") {
        e.preventDefault(); document.body.classList.toggle("wide"); return;
      }
    }
    if (e.key === " " && mode === "image") {
      e.preventDefault(); scroller.scrollTop += scroller.clientHeight * 0.9;
    }
  });

  /* ------------------------------------------------------------------ */
  /* sidebar trees                                                      */
  /* ------------------------------------------------------------------ */

  var sidebar = document.getElementById("sidebar");
  var docsTree = document.getElementById("docsTree");
  var filesTree = document.getElementById("filesTree");

  function callAsync(name) {
    var args = Array.prototype.slice.call(arguments, 1);
    var api = window.pywebview && window.pywebview.api;
    if (!bridgeKey || !api || typeof api.dispatch !== "function") return Promise.reject("no bridge");
    try { return Promise.resolve(api.dispatch(bridgeKey, name, args)); }
    catch (err) { return Promise.reject(err); }
  }

  /* Every expanded folder, so Python can restore the tree after a repaint.
     Keys rather than paths, so two roots showing one folder stay independent. */
  function expandedKeys() {
    return Array.prototype.map.call(
      filesTree ? filesTree.querySelectorAll(".node.open[data-dir='1']") : [],
      function (n) { return n.dataset.key; }
    );
  }

  /* Folders collapsed in the open-documents tree. */
  function collapsedDocPaths() {
    return Array.prototype.map.call(
      docsTree ? docsTree.querySelectorAll(".node[data-dir='1']:not(.open)") : [],
      function (n) { return n.dataset.path; }
    );
  }

  /* Sent straight away rather than debounced: clicking a file replaces the
     whole page, and a pending timer would die with it, losing the toggle. */
  function persistTree(kind) {
    if (kind === "files") call("set_expanded", expandedKeys());
    else call("set_doc_collapsed", collapsedDocPaths());
  }

  var KEY_SEP = "\u001f";

  function makeNode(item, depth, kind, rootId) {
    var node = document.createElement("div");
    node.className = "node";
    node.dataset.path = item.path || "";
    node.dataset.dir = item.dir ? "1" : "0";
    // Scoped by root: the same folder reached from two roots is two rows,
    // each with its own open/closed state.
    node.dataset.root = item.root || rootId || "";
    node.dataset.key = item.key || (node.dataset.root + KEY_SEP + node.dataset.path);

    var row = document.createElement("div");
    row.className = "row" + (item.dir ? " dir" : " file")
                  + (item.active ? " active" : "") + (item.stale ? " stale" : "");
    row.style.paddingLeft = (6 + depth * 12) + "px";
    row.title = item.path || item.name;
    if (typeof item.tab === "number") row.dataset.tab = item.tab;

    var chev = document.createElement("span");
    chev.className = "chev" + (item.dir ? "" : " leaf");
    chev.textContent = "▶";
    row.appendChild(chev);

    var ico = document.createElement("span");
    ico.className = "ico";
    ico.textContent = item.dir ? "\u{1F4C1}" : glyphFor(item.name);
    row.appendChild(ico);

    var nm = document.createElement("span");
    nm.className = "nm";
    nm.textContent = item.name;
    row.appendChild(nm);

    var dot = document.createElement("span");
    dot.className = "dot";
    row.appendChild(dot);

    // Open documents get a close button, mirroring the tab strip.
    if (kind === "docs" && !item.dir && typeof item.tab === "number") {
      var x = document.createElement("button");
      x.className = "x";
      x.type = "button";
      x.dataset.close = item.tab;
      x.title = "Close " + item.name;
      x.innerHTML = "&times;";
      row.appendChild(x);
    }

    node.appendChild(row);

    if (item.dir) {
      var kids = document.createElement("div");
      kids.className = "kids";
      node.appendChild(kids);
      if (item.children) {
        fillKids(kids, item.children, depth + 1, kind, item.more, node.dataset.root);
        node.dataset.loaded = "1";
        // Children are rendered even for a collapsed folder, so honour the flag.
        if (item.open !== false) node.classList.add("open");
      }
      if (item.open && !item.children) node.dataset.loaded = "";
    }
    return node;
  }

  function glyphFor(name) {
    var ext = (name.split(".").pop() || "").toLowerCase();
    if (ext === "mmd" || ext === "mermaid") return "◇";
    if (ext === "svg") return "◩";
    if (["png", "jpg", "jpeg", "gif", "webp", "bmp", "ico", "apng", "avif"].indexOf(ext) >= 0) {
      return "▦";
    }
    return "▬";
  }

  function fillKids(container, children, depth, kind, more, rootId) {
    container.textContent = "";
    children.forEach(function (child) {
      container.appendChild(makeNode(child, depth, kind, rootId));
    });
    if (more) {
      var row = document.createElement("div");
      row.className = "row more";
      row.style.paddingLeft = (6 + depth * 12) + "px";
      row.textContent = "… " + more + " more";
      container.appendChild(row);
    }
  }

  function paintTree(container, nodes, kind, emptyText) {
    if (!container) return;
    container.textContent = "";
    if (!nodes || !nodes.length) {
      var msg = document.createElement("div");
      msg.className = "empty";
      msg.textContent = emptyText;
      container.appendChild(msg);
      return;
    }
    nodes.forEach(function (n) { container.appendChild(makeNode(n, 0, kind, n.root)); });
  }

  function depthOf(node) {
    var depth = 0, cursor = node.parentElement;
    while (cursor && cursor !== docsTree && cursor !== filesTree) {
      if (cursor.classList.contains("kids")) depth++;
      cursor = cursor.parentElement;
    }
    return depth;
  }

  function toggleDir(node, kind) {
    if (node.classList.contains("open")) {
      node.classList.remove("open");
      persistTree(kind);
      return;
    }
    if (node.dataset.loaded === "1") {
      node.classList.add("open");
      persistTree(kind);
      return;
    }
    var chev = node.querySelector(":scope > .row > .chev");
    if (chev) chev.classList.add("spin");
    callAsync("list_dir", node.dataset.path).then(function (result) {
      if (chev) chev.classList.remove("spin");
      var kids = node.querySelector(":scope > .kids");
      if (!kids) return;
      node.dataset.loaded = "1";
      var entries = (result && result.entries) || [];
      if (!entries.length) {
        kids.textContent = "";
        var row = document.createElement("div");
        row.className = "row " + (result && result.denied ? "denied" : "more");
        row.style.paddingLeft = (6 + (depthOf(node) + 1) * 12) + "px";
        row.textContent = result && result.denied ? "not readable" : "empty";
        kids.appendChild(row);
      } else {
        fillKids(kids, entries, depthOf(node) + 1, kind, result.more,
                 node.dataset.root);
      }
      node.classList.add("open");
      persistTree(kind);
    }, function () {
      if (chev) chev.classList.remove("spin");
    });
  }

  function wireTree(container, kind) {
    if (!container) return;
    container.addEventListener("click", function (e) {
      var closer = e.target.closest("button[data-close]");
      if (closer) {
        e.stopPropagation();
        call("close_tab", parseInt(closer.dataset.close, 10));
        return;
      }
      var row = e.target.closest(".row");
      if (!row || row.classList.contains("more") || row.classList.contains("denied")) return;
      var node = row.parentElement;
      if (row.classList.contains("dir")) { toggleDir(node, kind); return; }
      if (kind === "docs") {
        if (row.dataset.tab !== undefined) call("select_tab", parseInt(row.dataset.tab, 10));
      } else {
        call("open_from_tree", node.dataset.path);
      }
    });
    container.addEventListener("dblclick", function (e) {
      // Double-clicking a folder name should not select text.
      if (e.target.closest(".row.dir")) e.preventDefault();
    });
  }

  paintTree(docsTree, CFG.docsTree, "docs", "No documents open.");
  paintTree(filesTree, CFG.filesTree, "files", "No drives available.");
  wireTree(docsTree, "docs");
  wireTree(filesTree, "files");

  var docsCount = document.getElementById("docsCount");
  if (docsCount) docsCount.textContent = CFG.tabCount ? String(CFG.tabCount) : "";

  /* keep the active document visible in the open-documents tree */
  var activeRow = docsTree && docsTree.querySelector(".row.active");
  if (activeRow && activeRow.scrollIntoView) {
    activeRow.scrollIntoView({ block: "nearest" });
  }

  /* ---- pane collapse ---- */
  function applyPanes(state) {
    ["docs", "files"].forEach(function (name) {
      var pane = document.getElementById(name === "docs" ? "paneDocs" : "paneFiles");
      if (pane) pane.classList.toggle("collapsed", state[name] === false);
    });
  }
  var paneState = { docs: CFG.panes.docs !== false, files: CFG.panes.files !== false };
  applyPanes(paneState);

  on("revealBtn", function (e) {
    e.stopPropagation();          // do not collapse the pane we are revealing in
    call("reveal_active");
  });

  Array.prototype.forEach.call(document.querySelectorAll(".pane > header"), function (h) {
    h.addEventListener("click", function (e) {
      if (e.target.closest(".reveal")) return;
      var name = h.dataset.pane;
      paneState[name] = !paneState[name];
      applyPanes(paneState);
      call("set_sidebar", !document.body.classList.contains("no-sidebar"),
           currentWidth(), paneState, currentDocsHeight());
    });
  });

  /* ---- show / hide ---- */
  function currentWidth() {
    var raw = document.body.style.getPropertyValue("--sidebar-w");
    return parseInt(raw, 10) || CFG.sidebarWidth || 264;
  }

  function currentDocsHeight() {
    var raw = document.body.style.getPropertyValue("--docs-h");
    return parseInt(raw, 10) || CFG.docsHeight || 220;
  }

  /* ---- the separator between the two trees ---- */
  var paneGrip = document.getElementById("paneGrip");
  if (paneGrip && sidebar) {
    var vdrag = null;
    paneGrip.addEventListener("pointerdown", function (e) {
      var docsPane = document.getElementById("paneDocs");
      if (!docsPane || docsPane.classList.contains("collapsed")) return;
      vdrag = { y: e.clientY, h: docsPane.offsetHeight };
      paneGrip.classList.add("dragging");
      paneGrip.setPointerCapture(e.pointerId);
      e.preventDefault();
    });
    paneGrip.addEventListener("pointermove", function (e) {
      if (!vdrag) return;
      // Leave room for the Computer pane's own header and a few rows.
      var ceiling = Math.max(80, sidebar.clientHeight - 120);
      var next = Math.max(60, Math.min(ceiling, vdrag.h + (e.clientY - vdrag.y)));
      document.body.style.setProperty("--docs-h", next + "px");
    });
    var endVDrag = function () {
      if (!vdrag) return;
      vdrag = null;
      paneGrip.classList.remove("dragging");
      call("set_sidebar", !document.body.classList.contains("no-sidebar"),
           currentWidth(), paneState, currentDocsHeight());
    };
    paneGrip.addEventListener("pointerup", endVDrag);
    paneGrip.addEventListener("pointercancel", endVDrag);
    paneGrip.addEventListener("dblclick", function () {
      document.body.style.setProperty("--docs-h", "220px");   // back to the default
      call("set_sidebar", !document.body.classList.contains("no-sidebar"),
           currentWidth(), paneState, 220);
    });
  }

  function toggleSidebar() {
    var hidden = document.body.classList.toggle("no-sidebar");
    call("set_sidebar", !hidden, currentWidth(), paneState, currentDocsHeight());
    if (mode === "image" && fitMode) { zoom = fitZoom(); render(); }
  }
  on("sidebarBtn", toggleSidebar);

  /* ---- resize ---- */
  var grip = document.getElementById("sideResize");
  if (grip) {
    var drag = null;
    grip.addEventListener("pointerdown", function (e) {
      drag = { x: e.clientX, w: currentWidth() };
      grip.classList.add("dragging");
      grip.setPointerCapture(e.pointerId);
      e.preventDefault();
    });
    grip.addEventListener("pointermove", function (e) {
      if (!drag) return;
      var next = Math.max(160, Math.min(640, drag.w + (e.clientX - drag.x)));
      document.body.style.setProperty("--sidebar-w", next + "px");
    });
    var endDrag = function () {
      if (!drag) return;
      drag = null;
      grip.classList.remove("dragging");
      call("set_sidebar", !document.body.classList.contains("no-sidebar"),
           currentWidth(), paneState, currentDocsHeight());
      if (mode === "image" && fitMode) { zoom = fitZoom(); render(); }
    };
    grip.addEventListener("pointerup", endDrag);
    grip.addEventListener("pointercancel", endDrag);
  }

  /* ------------------------------------------------------------------ */
  /* find in document                                                   */
  /* ------------------------------------------------------------------ */

  var findBar = document.getElementById("findbar");
  var findInput = document.getElementById("findInput");
  var findCount = document.getElementById("findCount");
  var findRanges = [];
  var findIndex = -1;
  var findTimer = null;
  var FIND_CAP = 5000;
  var CAN_HIGHLIGHT = typeof CSS !== "undefined" && !!CSS.highlights &&
                      typeof Highlight === "function";

  /* Ranges over the document's text, one per occurrence. A match straddling two
     text nodes (bold in the middle of a phrase) is not found: spanning them would
     mean rewriting the tree, which is exactly what this approach avoids. */
  function collectMatches(query) {
    var out = [];
    if (!query || !CAN_HIGHLIGHT || !content) return out;
    var needle = query.toLowerCase();
    var walker = document.createTreeWalker(content, NodeFilter.SHOW_TEXT, {
      acceptNode: function (node) {
        if (!node.data) return NodeFilter.FILTER_REJECT;
        var parent = node.parentElement;
        if (!parent) return NodeFilter.FILTER_REJECT;
        var tag = parent.tagName;
        if (tag === "SCRIPT" || tag === "STYLE") return NodeFilter.FILTER_REJECT;
        return NodeFilter.FILTER_ACCEPT;
      }
    });
    var node;
    while ((node = walker.nextNode())) {
      var hay = node.data.toLowerCase();
      var at = hay.indexOf(needle);
      while (at >= 0) {
        var range = document.createRange();
        range.setStart(node, at);
        range.setEnd(node, at + needle.length);
        out.push(range);
        if (out.length >= FIND_CAP) return out;
        at = hay.indexOf(needle, at + needle.length);
      }
    }
    return out;
  }

  function paintMatches() {
    if (!CAN_HIGHLIGHT) return;
    CSS.highlights.delete("mdv-find");
    CSS.highlights.delete("mdv-find-current");
    if (!findRanges.length) return;
    var rest = new Highlight();
    findRanges.forEach(function (r, i) { if (i !== findIndex) rest.add(r); });
    CSS.highlights.set("mdv-find", rest);
    if (findIndex >= 0 && findRanges[findIndex]) {
      // The current match sits in its own highlight, so it always paints on top.
      CSS.highlights.set("mdv-find-current", new Highlight(findRanges[findIndex]));
    }
  }

  function updateFindCount() {
    if (!findCount || !findInput) return;
    var hasQuery = !!findInput.value;
    findBar.classList.toggle("none", hasQuery && findRanges.length === 0);
    findCount.textContent = !hasQuery ? ""
      : findRanges.length ? (findIndex + 1) + " / " + findRanges.length
      : "0 / 0";
    var prev = document.getElementById("findPrev");
    var next = document.getElementById("findNext");
    if (prev) prev.disabled = findRanges.length < 1;
    if (next) next.disabled = findRanges.length < 1;
  }

  function scrollToMatch() {
    if (findIndex < 0 || !findRanges[findIndex] || !scroller) return;
    var rect = findRanges[findIndex].getBoundingClientRect();
    if (!rect || (!rect.width && !rect.height)) return;
    var box = scroller.getBoundingClientRect();
    var margin = 56;
    if (rect.top < box.top + margin || rect.bottom > box.bottom - margin) {
      scroller.scrollTop += (rect.top - box.top) - scroller.clientHeight / 3;
    }
    if (rect.left < box.left + 8 || rect.right > box.right - 8) {
      scroller.scrollLeft += (rect.left - box.left) - scroller.clientWidth / 3;
    }
  }

  function runFind(fromStart) {
    if (!findInput) return;
    findRanges = collectMatches(findInput.value);
    if (!findRanges.length) findIndex = -1;
    else if (fromStart || findIndex < 0 || findIndex >= findRanges.length) findIndex = 0;
    paintMatches();
    updateFindCount();
    if (findIndex >= 0) scrollToMatch();
  }

  function stepFind(delta) {
    if (!findRanges.length) return;
    findIndex = (findIndex + delta + findRanges.length) % findRanges.length;
    paintMatches();
    updateFindCount();
    scrollToMatch();
  }

  function findOpen() {
    return !!findBar && !findBar.hidden;
  }

  function openFind() {
    if (!findBar || mode === "image" || mode === "blank") return;
    findBar.hidden = false;
    findInput.focus();
    findInput.select();
    if (findInput.value) runFind(true); else updateFindCount();
  }

  function closeFind() {
    if (!findBar) return;
    findBar.hidden = true;
    if (CAN_HIGHLIGHT) {
      CSS.highlights.delete("mdv-find");
      CSS.highlights.delete("mdv-find-current");
    }
    findRanges = [];
    findIndex = -1;
    findBar.classList.remove("none");
    call("set_find_query", findInput ? findInput.value : "");
  }

  if (findInput) {
    if (CFG.findQuery) findInput.value = CFG.findQuery;
    findInput.addEventListener("input", function () {
      clearTimeout(findTimer);
      findTimer = setTimeout(function () { runFind(true); }, 90);
    });
    findInput.addEventListener("keydown", function (e) {
      if (e.key === "Enter") { e.preventDefault(); stepFind(e.shiftKey ? -1 : 1); }
      else if (e.key === "Escape") { e.preventDefault(); closeFind(); }
    });
  }
  on("findBtn", openFind);
  on("findPrev", function () { stepFind(-1); });
  on("findNext", function () { stepFind(1); });
  on("findClose", closeFind);

  /* test hook */
  window.__mdv_find = {
    open: openFind, close: closeFind, step: stepFind, run: runFind,
    state: function () {
      return { open: findOpen(), total: findRanges.length, index: findIndex,
               label: findCount ? findCount.textContent : "",
               supported: CAN_HIGHLIGHT };
    }
  };

  /* ------------------------------------------------------------------ */
  /* tabs                                                               */
  /* ------------------------------------------------------------------ */

  var tabStrip = document.getElementById("tabs");
  if (tabStrip) {
    tabStrip.addEventListener("click", function (e) {
      var closer = e.target.closest("button[data-close]");
      if (closer) {
        e.stopPropagation();
        call("close_tab", parseInt(closer.dataset.close, 10));
        return;
      }
      if (e.target.closest("#newTab")) { call("new_tab"); return; }
      var tab = e.target.closest(".tab[data-index]");
      if (tab) call("select_tab", parseInt(tab.dataset.index, 10));
    });
    // Middle-click closes, as it does everywhere else.
    tabStrip.addEventListener("auxclick", function (e) {
      if (e.button !== 1) return;
      var tab = e.target.closest(".tab[data-index]");
      if (tab) { e.preventDefault(); call("close_tab", parseInt(tab.dataset.index, 10)); }
    });
    // Keep the active tab in view when the strip overflows.
    var sel = tabStrip.querySelector('.tab[aria-selected="true"]');
    if (sel && sel.scrollIntoView) sel.scrollIntoView({ block: "nearest", inline: "nearest" });
  }

  /* ------------------------------------------------------------------ */
  /* link handling: local docs open in-app, the web opens in the browser */
  /* ------------------------------------------------------------------ */

  document.addEventListener("click", function (e) {
    var a = e.target.closest && e.target.closest("a[href]");
    if (!a) return;
    var href = a.getAttribute("href") || "";
    if (href.charAt(0) === "#") return;                     // in-page anchor
    e.preventDefault();
    if (/^(https?|ftp|mailto):/i.test(href)) { call("open_external", href); }
    else { call("open_path", a.href || href); }
  });

  /* ------------------------------------------------------------------ */
  /* style menu                                                         */
  /* ------------------------------------------------------------------ */

  var STYLES = CFG.styles || ["light", "dark", "github", "github-ext"];
  var FONTS = CFG.fonts || ["system", "sans", "serif", "mono"];
  var MERMAID_THEME = { light: "neutral", dark: "dark", github: "default",
                        "github-ext": "default" };

  function currentStyle() {
    return document.documentElement.dataset.style || STYLES[0];
  }

  function currentFont() {
    return document.documentElement.dataset.font || FONTS[0];
  }

  /* Mark the chosen row in a menu. */
  function markMenu(menuEl, value) {
    if (!menuEl) return;
    menuEl.querySelectorAll("button[data-value]").forEach(function (b) {
      b.setAttribute("aria-checked", b.dataset.value === value ? "true" : "false");
    });
  }

  function applyStyle(name, opts) {
    if (STYLES.indexOf(name) < 0) return;
    document.documentElement.dataset.style = name;
    markMenu(document.getElementById("styleMenu"), name);
    var btn = document.getElementById("styleBtn");
    if (btn) btn.title = "Style: " + name + " (Ctrl+D cycles)";
    renderMermaid(name);
    if (!(opts && opts.silent)) persist();
  }
  window.__mdv_setStyle = applyStyle;

  /* Font is pure CSS: swap the attribute, no repaint, no re-render. */
  function applyFont(name, opts) {
    if (FONTS.indexOf(name) < 0) return;
    document.documentElement.dataset.font = name;
    markMenu(document.getElementById("fontMenu"), name);
    var btn = document.getElementById("fontBtn");
    if (btn) btn.title = "Font: " + name;
    if (!(opts && opts.silent)) {
      call("set_font", name);
      if (mode === "image" && fitMode) { zoom = fitZoom(); render(); }
    }
  }
  window.__mdv_setFont = applyFont;

  function cycleStyle() {
    var next = STYLES[(STYLES.indexOf(currentStyle()) + 1) % STYLES.length];
    applyStyle(next);
    toast(next.charAt(0).toUpperCase() + next.slice(1));
  }

  /* ---- generic popup menus ---- */

  function closeMenus(except) {
    Array.prototype.forEach.call(document.querySelectorAll(".menu"), function (m) {
      if (m === except) return;
      m.hidden = true;
      var owner = document.querySelector('[data-menu="' + m.id + '"]');
      if (owner) owner.setAttribute("aria-expanded", "false");
    });
  }

  function openMenu(menuEl, open) {
    if (!menuEl) return;
    var owner = document.querySelector('[data-menu="' + menuEl.id + '"]');
    var show = open === undefined ? menuEl.hidden : open;
    if (show) closeMenus(menuEl);
    menuEl.hidden = !show;
    if (owner) owner.setAttribute("aria-expanded", show ? "true" : "false");
    if (show) {
      var active = menuEl.querySelector('button[aria-checked="true"]') ||
                   menuEl.querySelector("button[data-value]");
      if (active) active.focus();
    }
  }

  function applyChoice(kind, value) {
    if (kind === "style") applyStyle(value);
    else if (kind === "font") applyFont(value);
  }

  Array.prototype.forEach.call(document.querySelectorAll("[data-menu]"), function (btn) {
    btn.addEventListener("click", function (e) {
      e.stopPropagation();
      openMenu(document.getElementById(btn.dataset.menu));
    });
  });

  Array.prototype.forEach.call(document.querySelectorAll(".menu"), function (menuEl) {
    menuEl.addEventListener("click", function (e) {
      var b = e.target.closest("button[data-value]");
      if (!b) return;
      applyChoice(menuEl.dataset.kind, b.dataset.value);
      openMenu(menuEl, false);
      var owner = document.querySelector('[data-menu="' + menuEl.id + '"]');
      if (owner) owner.focus();
    });
    menuEl.addEventListener("keydown", function (e) {
      var items = Array.prototype.slice.call(menuEl.querySelectorAll("button[data-value]"));
      var at = items.indexOf(document.activeElement);
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        var next = (at + (e.key === "ArrowDown" ? 1 : items.length - 1) + items.length)
                   % items.length;
        items[next].focus();
      }
    });
  });

  document.addEventListener("click", function (e) {
    if (!e.target.closest(".menu-wrap")) closeMenus(null);
  });

  function anyMenuOpen() {
    return !!document.querySelector(".menu:not([hidden])");
  }

  /* ---- csv column alignment ---- */
  on("alignBtn", function () {
    var btn = document.getElementById("alignBtn");
    if (btn) btn.setAttribute("aria-pressed",
      btn.getAttribute("aria-pressed") === "true" ? "false" : "true");
    call("toggle_csv_align");
  });

  /* ------------------------------------------------------------------ */
  /* mermaid                                                            */
  /* ------------------------------------------------------------------ */

  function renderMermaid(styleName) {
    var nodes = document.querySelectorAll("pre.mermaid");
    if (!nodes.length) return;
    if (typeof window.mermaid === "undefined") {
      nodes.forEach(function (n) {
        if (n.dataset.failed) return;
        n.dataset.failed = "1";
        n.innerHTML = '<span class="mdv-nomermaid">Mermaid renderer unavailable - run ' +
                      "<code>md-view.py --fetch-assets</code> while online to enable diagrams." +
                      "</span><br><br>" + escapeHtml(n.dataset.src || "");
      });
      return;
    }
    nodes.forEach(function (n) {
      n.removeAttribute("data-processed");
      n.textContent = n.dataset.src || n.textContent;
    });
    try {
      window.mermaid.initialize({
        startOnLoad: false,
        theme: MERMAID_THEME[styleName] || "default",
        fontFamily: getComputedStyle(document.body).fontFamily,
        maxTextSize: 500000,
        flowchart: { useMaxWidth: false },
        sequence: { useMaxWidth: false },
        gantt: ganttConfig(styleName, nodes)
      });
      window.mermaid.run({ nodes: nodes, suppressErrors: true });
    } catch (err) {
      console.error("mermaid", err);
    }
  }

  /* Gantt layout. Mermaid's defaults everywhere except github-ext, which
     also gets larger type and a left gutter wide enough for the longest
     section title (mermaid never wraps those, so they ran into the bars).
     Every value is given explicitly so switching back restores the defaults. */
  var GANTT_RE = /(^|\n)\s*gantt\b/;
  function ganttConfig(styleName, nodes) {
    if (styleName !== "github-ext") {
      return { useMaxWidth: false, fontSize: 11, sectionFontSize: 11,
               barHeight: 20, leftPadding: 75 };
    }
    var longest = 0;
    Array.prototype.forEach.call(nodes, function (n) {
      (n.dataset.src || "").split("\n").forEach(function (line) {
        var m = /^\s*section\s+(.+?)\s*$/i.exec(line);
        if (m && m[1].length > longest) longest = m[1].length;
      });
    });
    // The window's width at 100%, whatever the zoom: zooming in then makes
    // the chart wider than the window, so there is something to pan across,
    // instead of redrawing it to fit at a larger type size.
    var gutter = mode === "mermaid" ? 48 : 80;     // #content side padding
    return { useMaxWidth: false, fontSize: 13, sectionFontSize: 13, barHeight: 22,
             useWidth: Math.max(400, scroller.clientWidth - gutter),
             leftPadding: Math.max(75, Math.min(320, Math.round(longest * 7.5) + 24)) };
  }

  /* A gantt chart is drawn at a fixed width, once. In github-ext that width is
     the window's, so redraw when the window or the sidebar changes it. The
     scroller is watched rather than the content: zooming must not redraw. */
  if (window.ResizeObserver && scroller) {
    var ganttWidth = 0, ganttTimer = null;
    new ResizeObserver(function () {
      var w = scroller.clientWidth;
      if (!ganttWidth) { ganttWidth = w; return; }
      if (Math.abs(w - ganttWidth) < 2) return;
      ganttWidth = w;
      if (currentStyle() !== "github-ext" || typeof window.mermaid === "undefined") return;
      var hasGantt = Array.prototype.some.call(
        document.querySelectorAll("pre.mermaid"),
        function (n) { return GANTT_RE.test(n.dataset.src || ""); });
      if (!hasGantt) return;
      clearTimeout(ganttTimer);
      ganttTimer = setTimeout(function () { renderMermaid(currentStyle()); }, 200);
    }).observe(scroller);
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c];
    });
  }

  window.__mdv_mermaidReady = function () {
    renderMermaid(currentStyle());
  };

  /* ------------------------------------------------------------------ */
  /* python bridge helpers                                              */
  /* ------------------------------------------------------------------ */

  function call(name) {
    callAsync.apply(null, arguments).catch(function () {
      // The bridge may be loading, or the call may have replaced this page.
    });
  }

  /* report scroll position so a reload can restore it */
  window.__mdv_scroll = function () {
    var max = scroller.scrollHeight - scroller.clientHeight;
    return max > 0 ? scroller.scrollTop / max : 0;
  };

  /* ------------------------------------------------------------------ */
  /* wire up the toolbar                                                */
  /* ------------------------------------------------------------------ */

  function on(id, fn) {
    var el = document.getElementById(id);
    if (el) el.addEventListener("click", fn);
  }
  on("zoomIn", function () { step(+1); });
  on("zoomOut", function () { step(-1); });
  on("fitBtn", doFit);
  on("backBtn", function () { call("go_back"); });
  on("openBtn", function () { call("pick_file"); });
  on("pickFile", function () { call("pick_file"); });
  on("reloadBtn", function () { call("refresh"); });
  if (label) label.addEventListener("click", function () { setZoom(1); });

  /* ------------------------------------------------------------------ */
  /* boot                                                               */
  /* ------------------------------------------------------------------ */

  applyStyle(currentStyle(), { silent: true });
  applyFont(currentFont(), { silent: true });
  render();
  if (CFG.scroll && mode !== "image") {
    requestAnimationFrame(function () {
      var max = scroller.scrollHeight - scroller.clientHeight;
      if (max > 0) scroller.scrollTop = CFG.scroll * max;
    });
  }
})();
"""


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
    base_tag = f'<base href="{html.escape(base.as_uri() + "/", quote=True)}">' if base else ""
    # Only scripts carrying this page's nonce run. A document's own <script>
    # or onerror= would otherwise reach window.pywebview.api.
    import secrets
    nonce = secrets.token_urlsafe(16)

    mermaid_tag = ""
    if with_mermaid:
        path = find_mermaid()
        if path:
            src = path.as_uri()
        else:
            src = MERMAID_CDN  # last resort; works only if the machine is online
        # The second script runs once the first has loaded or failed.
        mermaid_tag = (
            f'<script nonce="{nonce}" src="{html.escape(src, quote=True)}"></script>'
            f'<script nonce="{nonce}">__mdv_mermaidReady()</script>'
        )

    return f"""<!doctype html>
<html lang="en" data-style="{style}" data-font="{font}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'self' file: data: blob: https:; script-src 'nonce-{nonce}'; style-src 'unsafe-inline' file:; img-src file: data: blob: https:; object-src 'none'; frame-src 'none';">
<title>{html.escape(title)} - {APP_NAME}</title>
{base_tag}
<style>{BASE_CSS}
{pygments_css()}
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
<script nonce="{nonce}">window.__MDV__ = {json.dumps(cfg)};</script>
<script nonce="{nonce}">{VIEWER_JS}</script>
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


def read_text(path: Path) -> str:
    data = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


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


_WIN_HIDDEN_ATTRS = 0x2 | 0x4   # FILE_ATTRIBUTE_HIDDEN | FILE_ATTRIBUTE_SYSTEM
_IS_WINDOWS = sys.platform == "win32"
_IS_MAC = sys.platform == "darwin"


def _is_hidden(entry: os.DirEntry) -> bool:
    """Skip dot-files and, on Windows, hidden/system entries."""
    if entry.name.startswith("."):
        return True
    if _IS_WINDOWS:
        try:
            # scandir already fetched the attributes on Windows: no extra syscall.
            return bool(entry.stat(follow_symlinks=False).st_file_attributes
                        & _WIN_HIDDEN_ATTRS)
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


def filesystem_roots(anchor: Path | None = None) -> list[dict]:
    """Starting points for the computer tree.

    `anchor` is fixed for the session by the caller. It must not follow the
    documents around: recomputing it would reshape the tree whenever a file was
    opened, discarding whatever the reader had expanded and, if the new anchor
    happened to be an already-expanded folder, dumping all of its children.
    """
    roots: list[dict] = []
    seen: set[str] = set()

    def add(root_id: str, label: str, path: Path | None) -> None:
        if path is None:
            return
        try:
            if not path.is_dir():
                return
            key = str(path.resolve()).lower()
        except OSError:
            return
        if key in seen:
            return
        seen.add(key)
        roots.append({"name": label, "path": str(path), "dir": True,
                      "root": root_id, "key": node_key(root_id, path)})

    if anchor is not None:
        add("anchor", f"{anchor.name or anchor} (documents)", anchor)
    home = Path.home()
    add("home", "Home", home)
    for folder in ("Desktop", "Documents", "Downloads"):
        add(folder.lower(), folder, home / folder)

    if sys.platform == "win32":
        for letter in _windows_drives():
            add(f"drive-{letter.lower()}", f"{letter}:\\", Path(f"{letter}:\\"))
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


def _parse_document(path: Path, *, csv_align: bool = False) -> dict:
    """The expensive half of rendering: read the file and produce a body."""
    kind = classify(path)

    if kind == "markdown":
        body = rewrite_urls(render_markdown(read_text(path))[0], path.parent)
        return {"body": body, "mode": "doc", "subtitle": "", "base": path.parent,
                "with_mermaid": 'class="mermaid"' in body, "vector": False, "view_box": None}

    if kind == "mermaid":
        return {"body": mermaid_block(read_text(path)), "mode": "mermaid", "subtitle": "",
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
                "subtitle": f"{len(rows):,} × {columns}",
                "with_mermaid": False, "vector": False, "view_box": None, "csv": True}

    # plain text / unknown: show it verbatim rather than guessing
    return {"body": f"<pre><code>{html.escape(read_text(path))}</code></pre>",
            "mode": "doc", "subtitle": "", "base": path.parent,
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
        self.prefs = load_prefs()
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

    # F5 and the toolbar button both mean "rebuild this tab".
    reload = refresh

    def open_path(self, raw: str, *, new_tab: bool = False) -> bool:
        """Open a link target: viewable files in-app, anything else via the OS."""
        base = self.current.parent if self.current else Path.cwd()
        path = _path_from_href(raw, base)
        if path is None:
            return False
        # On macOS a folder with an extension may be a bundle (.app, .prefPane)
        # that `open` launches, so it is asked about below like a program.
        if path.is_dir() and not (_IS_MAC and path.suffix):
            _os_open(path)
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
            _os_open(path)
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
            try:
                watched = [t.path for t in list(self.tabs) if t.path is not None]
            except (IndexError, RuntimeError):
                continue
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
        save_prefs(self.prefs)

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

    reload = refresh

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
    def close_window(self):
        if self._window is not None:
            self._window.destroy()

    def toggle_fullscreen(self):
        if self._window is not None:
            self._window.toggle_fullscreen()

    def escape(self):
        return None

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
                    opened = 0
                    for item in message.get("paths") or []:
                        path = Path(item)
                        if path.exists():
                            self.viewer.open_tab(path)
                            opened += 1
                    if opened:
                        # Only a hand-off from another process brings the
                        # window forward; in-app opens leave it alone.
                        self.viewer._raise()
                    conn.sendall(b"ok" if opened else b"empty")
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
    return data_dir() / "instance.json"


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
            return Path(local).resolve()
        return (base / url2pathname(raw)).resolve()
    except (OSError, ValueError):
        return None


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
        _markdown_module()
        pygments_css()
    except Exception:
        pass        # purely a head start; the real render reports any problem


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.register:
        return register_associations()
    if args.unregister:
        return unregister_associations()
    if args.fetch_assets:
        return 0 if fetch_mermaid(force=args.force) else 1

    prefs = load_prefs()
    style = resolve_style(args.style, prefs)
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
    # opened one after another from Explorer.
    if paths and not args.new_window and hand_off(paths):
        return 0

    # Grab mermaid the first time it is actually needed, so the very first
    # launch of a diagram is not silently broken.
    if not args.no_mermaid and find_mermaid() is None:
        def wants_mermaid(p: Path) -> bool:
            kind = classify(p)
            if kind == "mermaid":
                return True
            return kind == "markdown" and "mermaid" in read_text(p).lower()

        if any(wants_mermaid(p) for p in paths):
            fetch_mermaid(timeout=30)

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
    if not args.new_window:
        try:
            viewer._server = InstanceServer(viewer)
        except OSError as exc:
            # Without a listener we simply lose single-instance behaviour.
            print(f"{APP_NAME}: single-instance listener unavailable ({exc})", file=sys.stderr)
    viewer.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
