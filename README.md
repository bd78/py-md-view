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
| Delimited | `.csv` `.tsv` `.tab` | one colour per column, with optional column alignment |
| Vector | `.svg` `.svgz` | scales as vector at any zoom |
| Raster | `.png` `.jpg` `.jpeg` `.gif` `.webp` `.bmp` `.ico` `.apng` `.avif` | zoom and drag to pan |
| Text | `.txt` `.log` `.json` `.yml` `.toml` `.ini` `.rst` | shown verbatim |

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
md-view.py --style github notes.md   # or --github-ext, --light, --dark
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
to resize, and click either pane's header to collapse just that pane. Drag the
separator between the two trees to change how the height is split, or
double-click it to go back to the default. Width, the split, visibility,
collapsed panes and expanded folders are all remembered.

**Open documents** — the files you have open, arranged by their own directory
structure. Only folders that actually contain an open document appear, and
chains of single sub-directories are folded into one row, so the tree stays
short. Clicking a document switches to its tab; the active one is highlighted
and a file changed on disk shows the same dot as its tab. Each document carries
a × on its right to close it, mirroring the tab strip.

**Computer** — browse for something to open. Clicking a file opens it in a new
tab. The roots are the
folder your documents were opened from, then Home, Desktop, Documents, Downloads
and the drives.

That first root is **fixed when the window opens** and never moves afterwards.
Deriving it from the documents you happen to have open would reshape the tree
every time you opened a file — discarding whatever you had expanded, and, if the
new root were a folder you had already expanded, dumping all of its children on
screen. The ◉ button in the pane header expands the tree down to the document
currently on screen.

Only directories and viewable files are listed — this tree exists to find
something to open, and hiding the rest keeps it readable. Dot-files and Windows
hidden/system entries are skipped, and a very long directory is capped with a
“… *n* more” row rather than pouring thousands of entries into the page.

Folders load lazily over the bridge and expand **without reloading the page**,
so opening a branch never re-renders your document or re-runs its diagrams.

Both trees keep whatever you expanded or collapsed. Opening a file rebuilds the
page, so that state is held on the Python side and reapplied — clicking a
document never re-opens folders you had closed.

Expansion is tracked per **root and path**, not by path alone. A folder you can
reach from two roots — a project under both Home and `C:\`, say — is two rows
with independent state, so expanding it in one place leaves the other as it was.

### Refresh

<kbd>F5</kbd> (or the toolbar's reload button) **rebuilds the active tab from
disk**, keeping your scroll position. Parsed documents are cached, so switching
tabs is instant; refresh is what forces a re-read.

md-view also watches every open file. A change to the document you are looking
at reloads it automatically; a change to a file in a background tab puts a dot
on that tab, and it rebuilds when you switch to it. Use `--no-watch` to turn
this off.

### Styles

Four looks, each with its own palette, syntax-highlighting theme and mermaid
theme. Pick one from the toolbar's style menu, cycle with
<kbd>Ctrl</kbd>+<kbd>D</kbd>, or press <kbd>1</kbd> to <kbd>4</kbd>:

- **Light** — neutral slate, quiet heading rules, roomy line height
- **Dark** — low-light palette
- **GitHub** — faithful to github.com's rendered Markdown
- **GitHub Ext** (the default) — GitHub's look, built for wide content. Text
  keeps its comfortable reading width, but everything else may use the whole
  window:
  - a table that does not fit the text column grows past it, centred, and
    only scrolls sideways if it is wider than the whole window;
  - an SVG standing on its own line, as an image or inline markup, is drawn
    across the full window width;
  - Mermaid diagrams are drawn at their natural size rather than shrunk, and
    Gantt charts stretch across the window with larger labels, redrawing
    when the window or sidebar changes width;
  - zoom magnifies the page instead of re-wrapping it, so you drag to move
    around a zoomed document (see Zoom).

The choice is remembered, along with your zoom level, in
`%LOCALAPPDATA%\md-view\prefs.json`. Without a saved preference the viewer
starts in GitHub Ext. Preferences saved before GitHub Ext existed are moved to
it once; pick another style afterwards and that choice sticks.

### Delimited files

`.csv`, `.tsv` and `.tab` files are rendered with **one colour per column**,
cycling through ten hues that adapt to the current style — the same idea as
Rainbow CSV. The delimiter is sniffed from the content (comma, semicolon, tab or
pipe; `.tsv`/`.tab` always mean tab), quoted fields containing delimiters or
newlines are handled properly, and the first row is shown in bold.

The **align button** in the toolbar — it appears only while a delimited file is
open — pads every field so the columns line up vertically. Turn it off to see the
file's own spacing again. The choice is remembered.

The file is shown as monospaced text rather than as a table, so its real shape
stays visible and alignment remains something you choose. Very wide files scroll
horizontally, and a file longer than 5,000 rows is cut off with a note saying so.

### Fonts

The **Aa** menu in the toolbar picks the body typeface:

- **System** — whatever the current style specifies
- **Sans** — the system UI sans
- **Serif** — Georgia / Cambria, with slightly looser leading
- **Monospace** — the code face throughout

Code blocks stay monospaced regardless. Switching is instant: it swaps one
attribute and changes no content, so nothing re-renders. `--font serif` sets it
from the command line, and the choice is remembered.

### Find

<kbd>Ctrl</kbd>+<kbd>F</kbd>, or the magnifier in the toolbar, opens a find bar
for the document on screen. It shows **which match you are on and how many there
are** — `3 / 17` — with arrows to step between them.

| | |
|---|---|
| <kbd>Ctrl</kbd>+<kbd>F</kbd> | open, or focus the bar if it is already open |
| <kbd>Enter</kbd> / <kbd>Shift</kbd>+<kbd>Enter</kbd> | next / previous match |
| <kbd>F3</kbd> / <kbd>Shift</kbd>+<kbd>F3</kbd> | next / previous, without leaving the document |
| <kbd>Esc</kbd> | close and clear the highlighting |

Every match is highlighted and the current one is picked out in a stronger
colour; stepping past the last match wraps to the first. Matching ignores case,
and the view scrolls to keep the current match on screen. Your search text is
remembered, so a refresh or a jump between tabs does not lose it.

Highlighting is painted with the browser's Custom Highlight API rather than by
inserting markup, so searching never disturbs the document — mermaid diagrams,
highlighted code and CSV colours stay exactly as they were. One consequence:
a match split across styling (`**wid**get`) is not found, because finding it
would mean rewriting the tree.

The bar searches the rendered document, so it works in Markdown, Mermaid, CSV
and text views. Images have no text to search, and the button is hidden there.

### Zoom

| Action | Keys |
|--------|------|
| Zoom in / out | <kbd>Ctrl</kbd>+<kbd>+</kbd> / <kbd>Ctrl</kbd>+<kbd>-</kbd>, <kbd>Ctrl</kbd>+wheel, or <kbd>+</kbd> / <kbd>-</kbd> |
| Reset to 100% | <kbd>Ctrl</kbd>+<kbd>0</kbd>, <kbd>0</kbd>, or click the percentage |
| Fit to window | <kbd>F</kbd>, or double-click an image |

Zoom keeps your place: <kbd>Ctrl</kbd>+wheel zooms about the pointer, and the
keys zoom about the middle of the view. SVG and Mermaid stay crisp at any
magnification because they are re-laid out rather than upscaled.

**Drag to move.** Hold the left button and drag to move around: anywhere on an
image, a diagram or a picture, and on the blank space of a document. A drag
that starts on text still selects that text, and clicking a link still follows
it.

How a document zooms depends on the style. In Light, Dark and GitHub it
reflows: the text re-wraps to fit the window. In **GitHub Ext** zoom magnifies
instead: the page keeps the layout it has at 100% and grows as a whole, so
zooming in makes it larger than the window and you drag to explore it, as you
would a zoomed image. Gantt charts grow with it rather than being redrawn to
fit.

### All shortcuts

| | |
|---|---|
| <kbd>Ctrl</kbd>+<kbd>F</kbd> | find in the document |
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
display is handed to the OS, after asking you first.

Scripts inside a document never run: the page only executes md-view's own
code, so a Markdown file cannot reach the viewer or start a program.

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
each page carries a `<base href>` pointing at the document's own folder, so
relative image and link paths resolve from there. The directory is removed on exit.

## Limitations

- Diagrams need the cached `mermaid.min.js`; without it md-view says so in
  place of the diagram and shows the source instead.
- The web view offers no find-in-page UI, so <kbd>Ctrl</kbd>+<kbd>F</kbd> does
  nothing.
- `--register` is Windows-only. On Linux, install a `.desktop` file; on macOS,
  wrap the script in a small app bundle.
- No editing. That is the point.
