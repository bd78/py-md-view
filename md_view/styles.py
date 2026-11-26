"""The page stylesheet (BASE_CSS) and the syntax-highlighting rules for every style."""

from __future__ import annotations

import functools

from .config import STYLE_PYGMENTS, STYLES


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
