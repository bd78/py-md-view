"""md-view, split into modules. md-view.py is the launcher; see spec/SPEC-package-split.md."""

from __future__ import annotations

__version__ = "1.0.0"

from . import (
    app,
    cli,
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
)
from .app import Viewer, Api, _drop_stale_bridge_replies
from .single_instance import InstanceServer, instance_file, instance_lock, hand_off
from .windows_assoc import register_associations, unregister_associations
from .config import DEFAULT_STYLE, MERMAID_SHA256, LAUNCHER
