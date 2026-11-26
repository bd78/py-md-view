"""```mermaid fences become diagrams -- but not when they are themselves an example."""


def diagrams(mdv, text):
    return mdv.markdown_render.render_markdown(text)[0].count('class="mermaid"')


def test_top_level_fence_is_a_diagram(mdv):
    assert diagrams(mdv, "```mermaid\ngraph TD; A-->B\n```\n") == 1


def test_fence_inside_a_longer_backtick_block_stays_code(mdv):
    text = "````markdown\n```mermaid\ngraph TD; A-->B\n```\n````\n"
    html = mdv.markdown_render.render_markdown(text)[0]
    assert diagrams(mdv, text) == 0
    assert "```mermaid" in html


def test_fence_inside_a_tilde_block_stays_code(mdv):
    assert diagrams(mdv, "~~~\n```mermaid\ngraph TD\n```\n~~~\n") == 0


def test_diagram_after_a_code_block_still_renders(mdv):
    text = "```python\nx = 1\n```\n\n```mermaid\ngraph TD\n```\n"
    assert diagrams(mdv, text) == 1


def test_inline_triple_backticks_do_not_open_a_block(mdv):
    text = "Use ```code``` here.\n\n```mermaid\ngraph TD\n```\n"
    assert diagrams(mdv, text) == 1


def test_fence_inside_raw_html_does_not_hide_later_diagram(mdv):
    text = "<pre>\n```\n</pre>\n\n```mermaid\ngraph TD; A-->B\n```\n"
    assert diagrams(mdv, text) == 1


def test_mermaid_fence_inside_raw_html_stays_literal(mdv):
    text = "<pre>\n```mermaid\ngraph TD; A-->B\n```\n</pre>\n"
    assert diagrams(mdv, text) == 0
