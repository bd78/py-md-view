"""CLI parser and application entry point."""

from __future__ import annotations

import argparse
import sys
import threading
import time
from pathlib import Path

from md_view import documents, mermaid_assets, styles
from md_view.app import Viewer
from md_view.config import APP_NAME, FONTS, STYLES, ZOOM_STEPS
from md_view.single_instance import hand_off, instance_lock, InstanceServer
from md_view.windows_assoc import register_associations, unregister_associations


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="md-view",
        description="Lightweight native viewer for Markdown, Mermaid, SVG and images.",
        epilog=(
            "Shortcuts: Ctrl++/Ctrl+- zoom, Ctrl+0 reset, F fit, W wide, "
            "F5 reload, Ctrl+F find, Ctrl+O open, Ctrl+B sidebar, "
            "Ctrl+D cycles style (or 1-4), "
            "[ back, F11 fullscreen."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("file", nargs="*", help="documents, sketches or images to display")
    p.add_argument("--zoom", type=float, metavar="F", help="initial zoom factor, e.g. 1.25")
    look = p.add_mutually_exclusive_group()
    look.add_argument("--style", choices=STYLES, dest="style",
                      help="presentation style (default: remembered, else github-ext)")
    look.add_argument("--dark", action="store_const", const="dark", dest="style",
                      help="shorthand for --style dark")
    look.add_argument("--light", action="store_const", const="light", dest="style",
                      help="shorthand for --style light")
    look.add_argument("--github", action="store_const", const="github", dest="style",
                      help="shorthand for --style github")
    look.add_argument("--github-ext", action="store_const", const="github-ext",
                      dest="style", help="shorthand for --style github-ext")
    p.add_argument("--font", choices=FONTS, dest="font",
                   help="body typeface (default: remembered, else the style's own)")
    p.add_argument("--no-watch", action="store_true",
                   help="do not reload when the file changes on disk")
    p.add_argument("--no-mermaid", action="store_true", help="skip mermaid rendering")
    p.add_argument("--register", action="store_true",
                   help="associate .md/.mmd with this viewer and add a right-click verb (Windows)")
    p.add_argument("--unregister", action="store_true", help="undo --register")
    p.add_argument("--fetch-assets", action="store_true",
                   help="download mermaid.js into the user cache for offline use")
    p.add_argument("--force", action="store_true", help="with --fetch-assets, re-download")
    p.add_argument("--new-window", action="store_true",
                   help="always start a separate window instead of adding a tab "
                        "to the running viewer")
    p.add_argument("--debug", action="store_true", help="open devtools and print tracebacks")
    p.add_argument("--version", action="version", version=f"{APP_NAME} {documents.__version__ if hasattr(documents, '__version__') else '1.0.0'}")
    return p


def _warm_renderers() -> None:
    """Import the markdown stack and build the highlight CSS, off the main thread."""
    try:
        documents.markdown_render._markdown_module()
        styles.pygments_css()
    except Exception:
        pass        # purely a head start; the real render reports any problem


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.register:
        return register_associations()
    if args.unregister:
        return unregister_associations()
    if args.fetch_assets:
        return 0 if mermaid_assets.fetch_mermaid(force=args.force) else 1

    from md_view import config
    prefs = config.load_prefs()
    style = config.resolve_style(args.style, prefs)
    font = args.font or prefs.get("font") or "system"
    if font not in FONTS:
        font = "system"
    zoom = args.zoom or float(prefs.get("zoom") or 1.0)
    zoom = min(ZOOM_STEPS[-1], max(ZOOM_STEPS[0], zoom))

    paths: list[Path] = []
    for item in args.file:
        path = Path(item).expanduser()
        try:
            path = path.resolve()
        except OSError:
            pass
        if not path.exists():
            print(f"{APP_NAME}: no such file: {path}", file=sys.stderr)
            return 1
        paths.append(path)

    # A viewer already running? Give it the files as new tabs instead of
    # starting a second window -- this is the common case when documents are
    # opened one after another from Explorer. When the owner is still starting
    # up, keep trying until its listener answers; the lock is released if the owner
    # dies, so the wait always ends, and giving up early would open a second window.
    owner = None if args.new_window else instance_lock()
    if paths and not args.new_window:
        while True:
            if hand_off(paths):
                return 0
            if owner is not None:
                break
            # A file deleted since the startup check would make the owner reply
            # "empty" for ever; stop once none is left.
            for gone in [p for p in paths if not p.exists()]:
                print(f"{APP_NAME}: no such file: {gone}", file=sys.stderr)
            paths = [p for p in paths if p.exists()]
            if not paths:
                return 1
            time.sleep(0.2)
            owner = instance_lock()     # the owner may have quit meanwhile

    # pywebview takes a few hundred milliseconds to import (it loads the .NET
    # bridge on Windows). Pull markdown and pygments in alongside it, so the
    # first document is ready to render the moment the window can show it.
    threading.Thread(target=_warm_renderers, daemon=True).start()
    try:
        import webview  # noqa: F401
    except ImportError:
        print(
            "pywebview is not installed. Run:\n"
            "    pip install -r requirements.txt\n"
            "or  pip install .",
            file=sys.stderr,
        )
        return 1

    viewer = Viewer(
        paths, style=style, zoom=zoom, font=font,
        watch=not args.no_watch, mermaid=not args.no_mermaid, debug=args.debug,
    )
    # Grab mermaid the first time it is actually needed, so the very first
    # launch of a diagram is not silently broken.
    if not args.no_mermaid and mermaid_assets.find_mermaid() is None:
        def wants_mermaid(p: Path) -> bool:
            kind = documents.classify(p)
            if kind == "mermaid":
                return True
            return kind == "markdown" and "mermaid" in documents.read_text(p).lower()

        if any(wants_mermaid(p) for p in paths):
            # In the background: on a network that drops the CDN this would hold
            # the window back for the whole timeout, on every launch. This
            # launch loads mermaid from the CDN instead (see page.build_page); when
            # the download lands, a page the CDN failed is repainted.
            def fetch_then_repaint() -> None:
                if mermaid_assets.fetch_mermaid(timeout=30, quiet=True):
                    viewer.mermaid_arrived()

            threading.Thread(target=fetch_then_repaint, daemon=True).start()

    if not args.new_window:
        try:
            viewer._server = InstanceServer(viewer)
        except OSError as exc:
            # Without a listener we simply lose single-instance behaviour.
            print(f"{APP_NAME}: single-instance listener unavailable ({exc})", file=sys.stderr)
            # Nobody can reach this window, so do not keep later launches waiting for it.
            if hasattr(owner, "close"):
                owner.close()
            owner = None
    viewer.run()
    return 0
