#!/usr/bin/env python3
"""md-view - a lightweight native viewer for Markdown, Mermaid, images and SVG.

Read-only by design: no editing, no autosave, nothing that can touch your files.

Usage:
    md-view.py DOCUMENT.md
    md-view.py sketch.mmd
    md-view.py diagram.svg
    md-view.py --register          # associate .md / .mmd with this viewer (Windows)
    md-view.py --fetch-assets      # pre-download mermaid.js for offline use

Author: bd78 (https://github.com/bd78)
"""

from __future__ import annotations

import sys
from pathlib import Path

# The md_view package sits next to this launcher (in the repo, or in site-packages after `pip install .`).
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from md_view import config, cli

config.LAUNCHER = Path(__file__).resolve()   # the package looks beside it for assets/


if __name__ == "__main__":
    sys.exit(cli.main())
