"""The parsers and rules the viewer leans on, checked without a window."""

import sys
from pathlib import Path

import pytest


# --- markdown ---------------------------------------------------------------

def test_mermaid_source_reaches_the_page_unmangled(mdv):
    body = mdv.render_markdown('```mermaid\ngraph TD; A["x & y"] --> B\n```\n')[0]
    assert 'class="mermaid"' in body
    # escaped once for HTML, never smart-quoted or highlighted
    assert 'data-src="graph TD; A[&quot;x &amp; y&quot;] --&gt; B"' in body


def test_task_lists_become_checkboxes(mdv):
    body = mdv.render_markdown("- [x] done\n- [ ] todo\n")[0]
    assert '<input type="checkbox" disabled checked>' in body
    assert body.count('type="checkbox"') == 2


# --- delimited files --------------------------------------------------------

def test_quoted_fields_keep_delimiters_and_newlines(mdv):
    rows, delimiter, truncated = mdv.parse_delimited('a,b\n"x, y","line1\nline2"\n', ".csv")
    assert delimiter == ","
    assert rows == [["a", "b"], ["x, y", "line1\nline2"]]
    assert not truncated


def test_semicolons_are_sniffed_and_tsv_is_always_tab(mdv):
    assert mdv.parse_delimited("a;b;c\n1;2;3\n", ".csv")[1] == ";"
    assert mdv.parse_delimited("a,b\tc\n", ".tsv")[1] == "\t"


def test_long_files_are_cut_and_say_so(mdv):
    text = "n\n" + "1\n" * (mdv.CSV_MAX_ROWS + 10)
    rows, _, truncated = mdv.parse_delimited(text, ".csv")
    assert len(rows) == mdv.CSV_MAX_ROWS and truncated
    html = mdv.render_delimited(rows, ",", aligned=False, truncated=True)
    assert "Showing the first" in html


def test_aligned_columns_are_padded_to_the_widest_field(mdv):
    html = mdv.render_delimited([["a", "b"], ["long", "c"]], ",", aligned=True, truncated=False)
    assert '<span class="c0">a&nbsp;&nbsp;&nbsp;</span>' in html


# --- links ------------------------------------------------------------------

@pytest.mark.skipif(sys.platform != "win32", reason="drive-letter URLs")
def test_file_url_with_drive_and_escapes(mdv):
    path = mdv._path_from_href("file:///C:/My%20Docs/notes.md#part", Path("D:/x"))
    assert path == Path("C:/My Docs/notes.md")


def test_relative_href_resolves_from_the_document(mdv, tmp_path):
    assert mdv._path_from_href("sub/a%20b.md", tmp_path) == (tmp_path / "sub" / "a b.md").resolve()
    assert mdv._path_from_href("#only-a-fragment", tmp_path) is None


# --- preferences ------------------------------------------------------------

def test_style_choice_rules(mdv):
    assert mdv.config.resolve_style(None, {}) == mdv.DEFAULT_STYLE
    # prefs from before github-ext existed move to the new default once ...
    assert mdv.config.resolve_style(None, {"style": "dark"}) == mdv.DEFAULT_STYLE
    # ... and a choice made after that sticks; an explicit flag always wins
    assert mdv.config.resolve_style(None, {"style": "dark", "style_default": mdv.DEFAULT_STYLE}) == "dark"
    assert mdv.config.resolve_style("light", {"style": "dark", "style_default": mdv.DEFAULT_STYLE}) == "light"


# --- sidebar ----------------------------------------------------------------

def test_open_documents_tree_folds_single_folder_chains(mdv, tmp_path):
    class Tab:
        def __init__(self, path):
            self.path = path

    a = tmp_path / "proj" / "docs" / "guide" / "a.md"
    b = tmp_path / "proj" / "docs" / "guide" / "b.md"
    c = tmp_path / "proj" / "notes" / "deep" / "c.md"
    roots = mdv.build_doc_tree([Tab(a), Tab(b), Tab(c)], active=1, stale={c})
    root = roots[0]
    names = [child["name"] for child in root["children"]]
    assert names == [f"docs{mdv.os.sep}guide", f"notes{mdv.os.sep}deep"]
    guide, deep = root["children"]
    assert [f["name"] for f in guide["children"]] == ["a.md", "b.md"]
    assert guide["children"][1]["active"] and deep["children"][0]["stale"]


def test_svg_without_size_uses_its_viewbox(mdv, tmp_path):
    svg = tmp_path / "s.svg"
    svg.write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 480"></svg>', "utf-8")
    assert mdv.svg_dimensions(svg) == (640.0, 480.0)
    svg.write_text('<svg width="10px" height="20" viewBox="0 0 640 480"></svg>', "utf-8")
    assert mdv.svg_dimensions(svg) is None
