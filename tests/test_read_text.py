"""read_text must cope with what Windows tools actually write."""

import pytest


@pytest.mark.parametrize("encoding", ["utf-16", "utf-16-be", "utf-8-sig", "utf-8"])
def test_unicode_files_decode(mdv, tmp_path, encoding):
    path = tmp_path / "out.log"
    text = "Héllo wörld\nline 2\n"
    data = text.encode(encoding)
    if encoding == "utf-16-be":
        data = b"\xfe\xff" + data        # big-endian with its BOM
    path.write_bytes(data)
    assert mdv.read_text(path) == text


def test_legacy_windows_text_still_decodes(mdv, tmp_path):
    path = tmp_path / "old.txt"
    path.write_bytes("café – 5 €".encode("cp1252"))
    assert mdv.read_text(path) == "café – 5 €"
