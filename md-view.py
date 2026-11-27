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

import argparse
import errno
import html
import json
import os
import re
import socket
import sys
import threading
import time
from pathlib import Path

# The md_view package sits next to this launcher (in the repo, or in site-packages after `pip install .`).
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from md_view import (
    __version__,
    app,
    config,
    documents,
    links,
    markdown_render,
    mermaid_assets,
    page,
    single_instance,
    styles,
    trees,
    viewer_js,
    windows_assoc,
    cli,
)
from md_view.app import Viewer, Api, _drop_stale_bridge_replies
from md_view.single_instance import InstanceServer, instance_file, instance_lock, hand_off
from md_view.windows_assoc import register_associations, unregister_associations
from md_view.cli import build_parser, main, _warm_renderers
from md_view.config import DEFAULT_STYLE, MERMAID_SHA256, LAUNCHER

config.LAUNCHER = Path(__file__).resolve()   # the package looks beside it for assets/


if __name__ == "__main__":
    sys.exit(main())
