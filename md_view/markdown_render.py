"""Markdown to HTML: the markdown stack, the mermaid fence preprocessor, task lists and inert meta tags."""

from __future__ import annotations

import html
import re


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
CODE_FENCE = re.compile(r"^[ ]{0,3}(?P<fence>`{3,}|~{3,})(?P<info>.*)$")
# Raw HTML blocks whose content is verbatim until the closing tag (CommonMark types 1 and 2).
RAW_HTML_OPEN = re.compile(r"^[ ]{0,3}<(?:(?P<tag>pre|script|style|textarea)\b|(?P<comment>!--))", re.IGNORECASE)


def _build_mermaid_extension():
    """A preprocessor that lifts ```mermaid fences out before any other parsing.

    Doing it at preprocessor level keeps the diagram source pristine: no
    smart-quoting, no syntax highlighting, no entity mangling of `-->` arrows.
    """
    from markdown.extensions import Extension
    from markdown.preprocessors import Preprocessor

    class MermaidPreprocessor(Preprocessor):
        def run(self, lines):
            out, i, raw_end = [], 0, None
            while i < len(lines):
                m = MERMAID_FENCE.match(lines[i])
                if raw_end is None and not m:
                    h = RAW_HTML_OPEN.match(lines[i])
                    if h:
                        raw_end = re.compile("-->" if h.group("comment") else "</" + h.group("tag") + r"\s*>", re.IGNORECASE)
                if raw_end is not None:
                    # A fence inside raw HTML is not a code block: copy through to the end tag.
                    out.append(lines[i])
                    if raw_end.search(lines[i]):
                        raw_end = None
                    i += 1
                    continue
                other = None if m else CODE_FENCE.match(lines[i])
                if other and other.group("fence")[0] == "`" and "`" in other.group("info"):
                    other = None    # ```inline``` code, not a fence
                if not m and not other:
                    out.append(lines[i])
                    i += 1
                    continue
                fence = (m or other).group("fence")
                close = re.compile(r"^[ ]{0,3}" + fence[0] + "{" + str(len(fence)) + r",}[ ]*$")
                if other:
                    # Any other code block is copied through untouched, so a
                    # ```mermaid line inside it stays an example.
                    out.append(lines[i])
                    i += 1
                    while i < len(lines) and not close.match(lines[i]):
                        out.append(lines[i])
                        i += 1
                    if i < len(lines):
                        out.append(lines[i])
                        i += 1
                    continue
                indent = len(m.group("indent"))
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
# Elements whose name (or, for <object>, id) becomes a property of `document`: a raw
# <img name="getElementById"> replaces that method for the whole page and stops the viewer script.
NAMED_TAG = re.compile(r"<(img|form|embed|iframe|object)(?=[\t\n\f\r />])", re.IGNORECASE)


def _unname_tags(html_text: str) -> str:
    """Rename name= (and id= on <object>) to data-mdv-*, so a document cannot shadow document methods.

    Attributes are read the way an HTML parser reads them: a name runs to whitespace, "/", ">" or "=",
    a value is a whole quoted string or an unquoted run, and the next attribute may follow a quote
    with no space. A regex over the tag either misses `alt=""name=x` or rewrites `src=a/name=b`.
    """
    out, pos, n = [], 0, len(html_text)
    for m in NAMED_TAG.finditer(html_text):
        if m.start() < pos:
            continue                       # inside a tag already scanned
        renamed = ("name", "id") if m.group(1).lower() == "object" else ("name",)
        out.append(html_text[pos:m.end()])
        i = m.end()
        while i < n and html_text[i] != ">":
            if html_text[i] in " \t\n\f\r/":
                out.append(html_text[i])
                i += 1
                continue
            j = i + 1                      # an attribute name; "=" may start one
            while j < n and html_text[j] not in " \t\n\f\r/>=":
                j += 1
            name = html_text[i:j]
            out.append("data-mdv-" + name if name.lower() in renamed else name)
            i = j
            k = i
            while k < n and html_text[k] in " \t\n\f\r":
                k += 1
            if k < n and html_text[k] == "=":
                k += 1
                while k < n and html_text[k] in " \t\n\f\r":
                    k += 1
                if k < n and html_text[k] in "\"'":
                    close = html_text.find(html_text[k], k + 1)
                    k = n if close < 0 else close + 1
                else:
                    while k < n and html_text[k] not in " \t\n\f\r>":
                        k += 1
                out.append(html_text[i:k])
                i = k
        pos = i
    out.append(html_text[pos:])
    return "".join(out)


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
        _build_mermaid_extension(),
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
    body = _unname_tags(body)
    return body, getattr(md, "toc", "")
