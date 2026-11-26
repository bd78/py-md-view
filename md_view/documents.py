"""What a document is and what it holds: file types, text reading, delimited text, SVG size, the parsed-document cache."""

from __future__ import annotations

import html
import re
from pathlib import Path

from . import markdown_render
from .config import CSV_COLOURS, CSV_EXTS, CSV_MAX_ROWS, MARKDOWN_EXTS, MERMAID_EXTS, RASTER_EXTS, SVG_EXTS


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
# The space before the unit sits inside the optional group, so "1<spaces>x" has one way to fail, not one per split.
SVG_ABSOLUTE_LEN = re.compile(r"^\s*[-\d.eE]+(?:\s*(?:px|pt|pc|cm|mm|in|Q))?\s*$", re.IGNORECASE)


def svg_dimensions(path: Path) -> tuple[float, float] | None:
    """Intrinsic size for an SVG, or None to trust what the engine reports.

    An SVG that declares only a viewBox has no intrinsic size, so the engine
    substitutes a placeholder (a 300x150 box shrunk to the viewBox aspect).
    Zooming from that placeholder makes "100%" meaningless, so in that case the
    viewBox extent is the honest natural size. When width/height *are* given in
    absolute units, the author stated a size and the engine already has it right.
    """
    try:
        with path.open("rb") as f:
            head = f.read(16384).decode("utf-8", errors="replace")
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
