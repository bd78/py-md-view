"""Relative URLs resolve through <base>; the body text itself is never rewritten."""


def test_text_that_looks_like_an_attribute_is_left_alone(mdv, tmp_path):
    doc = tmp_path / "doc.md"
    doc.write_text('Set `src="logo.png"` or write href="a.md" in prose.\n', "utf-8")
    parts = mdv.document_parts(doc)
    assert '<code>src="logo.png"</code>' in parts["body"]
    assert 'href="a.md" in prose' in parts["body"]
    assert parts["base"] == tmp_path
