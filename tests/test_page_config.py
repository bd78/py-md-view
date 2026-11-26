"""The page config is JSON inside <script>: it must not be able to end that tag."""

import json


def test_find_query_cannot_close_the_config_script(mdv):
    query = "</script><b>x</b>"
    page = mdv.page.build_page(body="<p>x</p>", title="t", mode="doc", style="github",
                          zoom=1.0, fit=False, scroll=0.0, base=None,
                          can_go_back=False, with_mermaid=False, find_query=query)
    # The HTML parser ends a script at the first "</script", whatever the JS says.
    start = page.index("window.__MDV__ = ") + len("window.__MDV__ = ")
    script = page[start:page.index("</script", start)]
    assert json.loads(script.rstrip(";"))["findQuery"] == query


def test_find_query_cannot_open_a_double_escaped_script(mdv):
    # "<!--<script>" puts the parser in a state where "</script>" no longer ends the tag.
    query = "<!--<script></script>"
    page = mdv.page.build_page(body="<p>x</p>", title="t", mode="doc", style="github",
                          zoom=1.0, fit=False, scroll=0.0, base=None,
                          can_go_back=False, with_mermaid=False, find_query=query)
    start = page.index("window.__MDV__ = ")
    end = page.index("</script>", start)
    assert "<!--" not in page[start:end] and "<script" not in page[start:end]
