"""HTML assembly: the page shell with its CSP and nonce, toolbar, tabs, sidebar, find bar, and the page per document."""

from __future__ import annotations

import html
import json
from pathlib import Path

from . import config, documents, mermaid_assets, styles, viewer_js
from .config import APP_NAME, FONT_LABELS, FONTS, MERMAID_CDN, STYLE_LABELS, STYLES, ZOOM_STEPS


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


def render_document(path: Path, *, style: str, zoom: float, fit: bool,
                    scroll: float, can_go_back: bool,
                    tabs: list[dict] | None = None, active_tab: int = 0,
                    sidebar: dict | None = None, font: str = "system",
                    csv_align: bool = False, find_query: str = "") -> str:
    parts = documents.document_parts(path, csv_align=csv_align)
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
