"""Load md-view.py as a module: the hyphen in its name rules out a plain import."""

import importlib.util
from pathlib import Path
import sys
import os
import time
import types

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(scope="session")
def mdv():
    spec = importlib.util.spec_from_file_location("mdview", ROOT / "md-view.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    import md_view
    import md_view.cli
    import md_view.config
    import md_view.app
    import md_view.single_instance
    import md_view.mermaid_assets
    import md_view.documents
    import md_view.markdown_render
    import md_view.styles
    import md_view.trees
    import md_view.page
    import md_view.links
    import md_view.windows_assoc
    import md_view.viewer_js

    md_view.config.LAUNCHER = ROOT / "md-view.py"

    class Mdproxy(types.ModuleType):
        def __setattr__(self, name, value):
            super().__setattr__(name, value)
            for submod in [md_view, md_view.cli, md_view.config, md_view.app, md_view.single_instance, md_view.mermaid_assets, md_view.documents, md_view.markdown_render, md_view.styles, md_view.trees, md_view.page, md_view.links, md_view.windows_assoc, md_view.viewer_js]:
                if hasattr(submod, name):
                    try:
                        setattr(submod, name, value)
                    except Exception:
                        pass

        def __getattr__(self, name):
            for submod in [md_view, md_view.cli, md_view.config, md_view.app, md_view.single_instance, md_view.mermaid_assets, md_view.documents, md_view.markdown_render, md_view.styles, md_view.trees, md_view.page, md_view.links, md_view.windows_assoc, md_view.viewer_js]:
                if hasattr(submod, name):
                    return getattr(submod, name)
            raise AttributeError(f"module 'mdview' has no attribute '{name}'")

    proxy = Mdproxy("mdview")
    proxy.__dict__.update(module.__dict__)

    for submod in [md_view.cli, md_view.config, md_view.app, md_view.single_instance, md_view.mermaid_assets, md_view.documents, md_view.markdown_render, md_view.styles, md_view.trees, md_view.page, md_view.links, md_view.windows_assoc, md_view.viewer_js]:
        proxy.__dict__[submod.__name__.split('.')[-1]] = submod
        for name in dir(submod):
            if not name.startswith("_") or name in ("_drop_stale_bridge_replies", "hand_off", "InstanceServer", "Viewer"):
                setattr(proxy, name, getattr(submod, name))

    proxy.os = os
    proxy.time = time
    proxy.pathlib = Path
    proxy.main = md_view.cli.main
    return proxy
