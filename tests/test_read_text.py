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


def test_huge_file_is_cut_at_a_line_not_read_whole(mdv, tmp_path, monkeypatch):
    monkeypatch.setattr(mdv, "MAX_TEXT_BYTES", 101)
    path = tmp_path / "big.log"
    path.write_bytes(("é\n" * 100).encode("utf-8"))       # 300 bytes, 2-byte letters
    text = mdv.read_text(path)
    assert 0 < len(text.encode("utf-8")) <= 101
    assert set(text) <= {"é", "\n"}                       # no split character, no mojibake


def test_cut_file_says_how_much_is_shown(mdv, tmp_path, monkeypatch):
    monkeypatch.setattr(mdv, "MAX_TEXT_BYTES", 100)
    path = tmp_path / "big.txt"
    path.write_text("x\n" * 500, "utf-8")
    assert "first" in mdv._parse_document(path)["subtitle"]
    small = tmp_path / "small.txt"
    small.write_text("x\n", "utf-8")
    assert mdv._parse_document(small)["subtitle"] == ""


def test_cut_inside_a_character_keeps_the_encoding(mdv, tmp_path, monkeypatch):
    monkeypatch.setattr(mdv, "MAX_TEXT_BYTES", 101)
    one_line = tmp_path / "min.json"
    one_line.write_bytes(("é" * 100).encode("utf-8"))      # no newline, 101 cuts a letter in two
    assert set(mdv.read_text(one_line)) == {"é"}

    monkeypatch.setattr(mdv, "MAX_TEXT_BYTES", 100)
    utf16 = tmp_path / "out.log"
    utf16.write_bytes(("A\n" * 200).encode("utf-16"))       # BOM + little-endian code units
    assert "�" not in mdv.read_text(utf16)


@pytest.mark.parametrize("data", [b"\xef", b"\xef\xbb"])
def test_partial_bom_file_is_shown_not_swallowed(mdv, tmp_path, data):
    path = tmp_path / "x.txt"
    path.write_bytes(data)
    assert mdv.read_text(path) == data.decode("cp1252")
