# md-view

A lightweight, native viewer for Markdown documents, Mermaid sketches, SVG and
common image formats. Read-only by design: it renders, zooms and reloads — it
never writes to your files.

It draws with the operating system's own web view (WebView2 on Windows, WebKit
elsewhere), so there is no bundled browser engine: the install is a few MB and
a window opens fast enough to sit behind a file association.

## What it opens

| Type | Extensions | Notes |
|------|-----------|-------|
| Markdown | `.md` `.markdown` `.mdown` `.mkd` `.mkdn` `.mdtext` | tables, footnotes, task lists, admonitions, definition lists, syntax highlighting, and ` ```mermaid ` blocks rendered as diagrams |
| Mermaid | `.mmd` `.mermaid` | the whole file is one diagram |
| Vector | `.svg` `.svgz` | scales as vector at any zoom |
| Raster | `.png` `.jpg` `.jpeg` `.gif` `.webp` `.bmp` `.ico` `.apng` `.avif` | zoom and drag to pan |
| Text | `.txt` `.log` `.json` `.yml` `.toml` `.ini` `.csv` `.rst` | shown verbatim |

## Install

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Then the two optional setup steps, both of which need nothing beyond the
standard library:

```powershell
.\.venv\Scripts\python.exe md-view.py --fetch-assets   # cache mermaid.js offline
.\.venv\Scripts\python.exe md-view.py --register       # associate .md / .mmd
```

`setup.py` wraps the same steps as `fetch_assets`, `register` and
`develop_local`, but it needs `setuptools` — which virtual environments on
Python 3.12+ no longer include. Either `pip install setuptools` first, or just
use the `md-view.py` flags above; they are the same code paths.

Mermaid rendering needs `mermaid.min.js` (~3.5 MB). It is downloaded on first
use and cached in `%LOCALAPPDATA%\md-view\assets\`. Fetch it ahead of time with
`--fetch-assets`, or drop your own copy in `./assets/mermaid.min.js` to ship it
alongside the script. Everything else works with no network at all.

## Use

```powershell
md-view.py report.md            # open a document
md-view.py a.md b.md sketch.mmd # each file gets a tab
md-view.py diagram.svg --dark
md-view.py --style github notes.md
```

### Tabs and single instance

Opening a document while md-view is already running adds a **tab** to the
existing window rather than starting a second process — which is what you want
when documents are opened one at a time from Explorer. The running instance is
found through a loopback port recorded in `%LOCALAPPDATA%\md-view\instance.json`,
guarded by a per-session token so nothing else on the machine can drive your
window. Pass `--new-window` to opt out and get a separate window.

Opening a file that is already in a tab just focuses that tab.

### Sidebar

The left sidebar holds two independent trees. Toggle the whole thing with
<kbd>Ctrl</kbd>+<kbd>B</kbd> or the toolbar's panel button, drag its right edge
to resize, and click either pane's header to collapse just that pane. Width,
visibility, collapsed panes and expanded folders are all remembered.

**Open documents** — the files you have open, arranged by their own directory
structure. Only folders that actually contain an open document appear, and
chains of single sub-directories are folded into one row, so the tree stays
short. Clicking a document switches to its tab; the active one is highlighted
and a file changed on disk shows the same dot as its tab.

**Computer** — browse for something to open. Clicking a file opens it in a new
tab; anything md-view cannot display is handed to the OS. The roots are the
folder containing your open documents, then Home, Desktop, Documents, Downloads
and the drives.

That first root is derived from *all* open documents rather than the active one,
on purpose: a root that changed identity every time you switched tabs would move
out from under whatever you had just expanded. The ◉ button in the pane header
expands the tree down to the document currently on screen.

Only directories and viewable files are listed — this tree exists to find
something to open, and hiding the rest keeps it readable. Dot-files and Windows
hidden/system entries are skipped, and a very long directory is capped with a
“… *n* more” row rather than pouring thousands of entries into the page.

Folders load lazily over the bridge and expand **without reloading the page**,
so opening a branch never re-renders your document or re-runs its diagrams.

### Refresh

<kbd>F5</kbd> (or the toolbar's reload button) **rebuilds the active tab from
disk**, keeping your scroll position. Parsed documents are cached, so switching
tabs is instant; refresh is what forces a re-read.

md-view also watches every open file. A change to the document you are looking
at reloads it automatically; a change to a file in a background tab puts a dot
on that tab, and it rebuilds when you switch to it. Use `--no-watch` to turn
this off.

### Styles

Three complete looks, each with its own palette, syntax-highlighting theme and
mermaid theme. Pick one from the toolbar's style menu, cycle with
<kbd>Ctrl</kbd>+<kbd>D</kbd>, or press <kbd>1</kbd> / <kbd>2</kbd> /
<kbd>3</kbd>:

- **Light** — neutral slate, quiet heading rules, roomy line height
- **Dark** — low-light palette
- **GitHub** — faithful to github.com's rendered Markdown

The choice is remembered, along with your zoom level, in
`%LOCALAPPDATA%\md-view\prefs.json`. Without a saved preference the viewer
follows the OS light/dark setting.

### Zoom

| Action | Keys |
|--------|------|
| Zoom in / out | <kbd>Ctrl</kbd>+<kbd>+</kbd> / <kbd>Ctrl</kbd>+<kbd>-</kbd>, <kbd>Ctrl</kbd>+wheel, or <kbd>+</kbd> / <kbd>-</kbd> |
| Reset to 100% | <kbd>Ctrl</kbd>+<kbd>0</kbd>, <kbd>0</kbd>, or click the percentage |
| Fit to window | <kbd>F</kbd>, or double-click an image |

Documents reflow as you zoom. Images and SVGs scale about the pointer and can
be dragged to pan once they overflow the window; SVG and Mermaid stay crisp at
any magnification because they are re-laid out rather than upscaled.

### All shortcuts

| | |
|---|---|
| <kbd>Ctrl</kbd>+<kbd>B</kbd> | show / hide the sidebar |
| <kbd>Ctrl</kbd>+<kbd>O</kbd> | open file(s) |
| <kbd>Ctrl</kbd>+<kbd>T</kbd> | open in a new tab |
| <kbd>Ctrl</kbd>+<kbd>W</kbd> | close tab (closes the window on the last one) |
| <kbd>Ctrl</kbd>+<kbd>Tab</kbd> / <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>Tab</kbd> | next / previous tab |
| <kbd>Ctrl</kbd>+<kbd>1</kbd>…<kbd>9</kbd> | jump to tab *n* |
| <kbd>F5</kbd> | rebuild this tab from disk |
| <kbd>[</kbd> / <kbd>]</kbd> | back / forward within a tab |
| <kbd>W</kbd> | toggle wide layout |
| <kbd>F11</kbd> | full screen |

Links to other local documents open in the current tab with working back and
forward; `http(s)` links go to your normal browser; anything md-view cannot
display is handed to the OS.

## File associations (Windows)

```powershell
md-view.py --register     # HKCU only, no administrator rights needed
md-view.py --unregister
```

This makes md-view the default handler for `.md`, `.markdown`, `.mdown`,
`.mkd`, `.mkdn`, `.mdtext`, `.mmd` and `.mermaid`, and adds a **“View with
md-view”** right-click entry for those plus every supported image type. Image
defaults are deliberately left alone.

It launches through `pythonw.exe` when available, so no console window flashes.

The registry stores absolute paths to both the interpreter and the script — run
it from your `.venv` and the association uses that venv, dependencies included.
Moving or deleting either path breaks the association; re-run `--register` after
moving the project to record the new location.

If Windows still opens another app for `.md` afterwards, that extension already
has a saved *UserChoice*, which only you can change: right-click a file →
**Open with** → **Choose another app** → md-view → **Always**.

## Layout

| Path | Purpose |
|------|---------|
| [md-view.py](md-view.py) | the whole application — one file, so it stays easy to copy and to point a registry command at |
| [setup.py](setup.py) | dependency install, `fetch_assets`, `register` |
| [requirements.txt](requirements.txt) | runtime dependencies |
| [samples/](samples/) | a demo document, a standalone sketch and an SVG |

Rendered pages are written to a temp directory and loaded as `file://` URLs;
relative image and link paths are rewritten to absolute URLs so they resolve
from there. The directory is removed on exit.

## Limitations

- Diagrams need the cached `mermaid.min.js`; without it md-view says so in
  place of the diagram and shows the source instead.
- The web view offers no find-in-page UI, so <kbd>Ctrl</kbd>+<kbd>F</kbd> does
  nothing.
- `--register` is Windows-only. On Linux, install a `.desktop` file; on macOS,
  wrap the script in a small app bundle.
- No editing. That is the point.
