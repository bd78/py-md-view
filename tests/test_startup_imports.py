"""The "hand the file to the running window" launch stays lean (AGENTS.md: lean start-up).

It runs in a fresh interpreter, so modules other tests imported do not hide a regression. The reference is
measured in that same interpreter, so it holds on every platform and Python version.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

# md-view.py's top-level imports. A new one belongs here only if the hand-off launch really needs it.
TOP_LEVEL = "argparse, errno, functools, html, json, os, re, socket, sys, threading, time, pathlib"

# The hand-off path of main() may add small standard-library modules (argparse pulls in shutil and
# locale, socket needs the idna codec, the lock needs msvcrt or fcntl; the exact set varies by Python
# version). It must not add a third-party module, nor one of these, which md-view imports only where used.
HEAVY_STDLIB = {"urllib", "secrets", "tempfile", "webbrowser", "csv", "hashlib", "ctypes", "winreg"}

# Plays the running window: answers one hand-off with "ok", then reports what each stage imported.
LAUNCH = r"""
import importlib.util, json, socket, sys, threading
import %s
before = set(sys.modules)
spec = importlib.util.spec_from_file_location("mdview", sys.argv[1])
mdv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mdv)
loaded = set(sys.modules)

server = socket.socket()
server.bind(("127.0.0.1", 0))
server.listen(1)
(mdv.data_dir() / "instance.json").write_text(
    json.dumps({"port": server.getsockname()[1], "token": "t", "pid": 0}), "utf-8")

def answer():
    conn, _ = server.accept()
    conn.recv(65536)
    conn.sendall(b"ok")
    conn.close()

threading.Thread(target=answer, daemon=True).start()
code = mdv.main([sys.argv[2]])
print(json.dumps({"code": code, "load": sorted(loaded - before), "main": sorted(set(sys.modules) - loaded)}))
""" % TOP_LEVEL


@pytest.mark.skipif(not hasattr(sys, "stdlib_module_names"), reason="needs Python 3.10+")
def test_hand_off_launch_imports_nothing_new(tmp_path):
    doc = tmp_path / "a.md"
    doc.write_text("# a", "utf-8")
    env = dict(os.environ, LOCALAPPDATA=str(tmp_path), XDG_DATA_HOME=str(tmp_path), HOME=str(tmp_path))
    out = subprocess.run(
        [sys.executable, "-c", LAUNCH, str(ROOT / "md-view.py"), str(doc)],
        env=env, capture_output=True, text=True, timeout=60, check=True,
    )
    result = json.loads(out.stdout.strip().splitlines()[-1])
    assert result["code"] == 0                      # the fake window took the file
    assert [m for m in result["load"] if m != "__future__" and not m.startswith("md_view")] == []
    tops = {m.split(".")[0] for m in result["main"]}
    assert sorted(tops - set(sys.stdlib_module_names)) == []        # markdown, webview, pygments, ...
    assert sorted(tops & HEAVY_STDLIB) == []
