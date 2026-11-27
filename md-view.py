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

# urllib.request, secrets, shutil, tempfile and webbrowser are imported where
# they are used: together they cost ~45 ms at start-up, and the common
# "hand the file to the running window" launch needs none of them.


# The md_view package sits next to this launcher (in the repo, or in site-packages after `pip install .`).
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from md_view import __version__, app, config, documents, links, markdown_render, mermaid_assets, page, single_instance, styles, trees, viewer_js  # noqa: E402

config.LAUNCHER = Path(__file__).resolve()   # the package looks beside it for assets/
from md_view.config import (  # noqa: E402
    APP_NAME, DEFAULT_STYLE, FONTS, IMAGE_EXTS, MARKDOWN_EXTS, MERMAID_EXTS, STYLE_BG, STYLES, VIEWABLE_EXTS, ZOOM_STEPS,
)
from md_view.app import Viewer, Api, _drop_stale_bridge_replies  # noqa: E402
from md_view.single_instance import InstanceServer, instance_file, instance_lock, hand_off  # noqa: E402


# --------------------------------------------------------------------------- #
# Windows file associations
# --------------------------------------------------------------------------- #

PROGIDS = {
    "markdown": ("md-view.markdown", "Markdown Document", sorted(MARKDOWN_EXTS)),
    "mermaid": ("md-view.mermaid", "Mermaid Diagram", sorted(MERMAID_EXTS)),
}
CONTEXT_MENU_EXTS = sorted(MARKDOWN_EXTS | MERMAID_EXTS | IMAGE_EXTS)
VERB_KEY = "md-view.open"


def _launch_command() -> tuple[str, str]:
    """Return (command, icon) for the registry, preferring a console-free launcher."""
    script = Path(__file__).resolve()
    exe = Path(sys.executable)
    pythonw = exe.with_name("pythonw.exe")
    launcher = pythonw if pythonw.is_file() else exe
    return f'"{launcher}" "{script}" "%1"', f'"{launcher}",0'


def register_associations() -> int:
    if sys.platform != "win32":
        print("--register currently supports Windows only.", file=sys.stderr)
        print("On Linux, install a .desktop file; on macOS, use a small app bundle.", file=sys.stderr)
        return 2

    import winreg

    command, icon = _launch_command()
    classes = r"Software\Classes"
    created = []

    def setval(root, sub, name, value, vtype=winreg.REG_SZ):
        with winreg.CreateKeyEx(root, sub, 0, winreg.KEY_WRITE) as key:
            winreg.SetValueEx(key, name, 0, vtype, value)

    for progid, label, exts in PROGIDS.values():
        setval(winreg.HKEY_CURRENT_USER, rf"{classes}\{progid}", "", label)
        setval(winreg.HKEY_CURRENT_USER, rf"{classes}\{progid}", "FriendlyTypeName", label)
        setval(winreg.HKEY_CURRENT_USER, rf"{classes}\{progid}\DefaultIcon", "", icon)
        setval(winreg.HKEY_CURRENT_USER, rf"{classes}\{progid}\shell\open", "", f"View with {APP_NAME}")
        setval(winreg.HKEY_CURRENT_USER, rf"{classes}\{progid}\shell\open\command", "", command)
        for ext in exts:
            # Default handler: honoured when the user has no explicit UserChoice.
            setval(winreg.HKEY_CURRENT_USER, rf"{classes}\{ext}", "", progid)
            # And always offer it in the "Open with" list.
            with winreg.CreateKeyEx(
                winreg.HKEY_CURRENT_USER, rf"{classes}\{ext}\OpenWithProgids", 0, winreg.KEY_WRITE
            ) as key:
                winreg.SetValueEx(key, progid, 0, winreg.REG_NONE, b"")
            created.append(ext)

    # A right-click verb, so the viewer is reachable even for types whose
    # default handler we deliberately leave alone (images, SVG).
    for ext in CONTEXT_MENU_EXTS:
        base = rf"{classes}\SystemFileAssociations\{ext}\shell\{VERB_KEY}"
        setval(winreg.HKEY_CURRENT_USER, base, "", f"View with {APP_NAME}")
        setval(winreg.HKEY_CURRENT_USER, base, "Icon", icon)
        setval(winreg.HKEY_CURRENT_USER, rf"{base}\command", "", command)

    _notify_shell()
    print(f"Registered {APP_NAME} for: {', '.join(created)}")
    print(f"Right-click 'View with {APP_NAME}' added for: {', '.join(CONTEXT_MENU_EXTS)}")
    print(f"Command: {command}")
    print()
    print("If Windows still opens another app for .md, that extension already has a")
    print("saved UserChoice. Fix it once via right-click > Open with > Choose another")
    print(f"app > {APP_NAME} > Always.")
    return 0


def unregister_associations() -> int:
    if sys.platform != "win32":
        print("--unregister currently supports Windows only.", file=sys.stderr)
        return 2

    import winreg

    classes = r"Software\Classes"

    def delete_tree(root, sub):
        try:
            with winreg.OpenKey(root, sub, 0, winreg.KEY_READ | winreg.KEY_WRITE) as key:
                while True:
                    try:
                        child = winreg.EnumKey(key, 0)
                    except OSError:
                        break
                    delete_tree(root, f"{sub}\\{child}")
            winreg.DeleteKey(root, sub)
            return True
        except FileNotFoundError:
            return False
        except OSError:
            return False

    removed = []
    for progid, _label, exts in PROGIDS.values():
        if delete_tree(winreg.HKEY_CURRENT_USER, rf"{classes}\{progid}"):
            removed.append(progid)
        for ext in exts:
            # Only reset the default if it still points at us.
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, rf"{classes}\{ext}", 0,
                                    winreg.KEY_READ | winreg.KEY_WRITE) as key:
                    try:
                        value, _ = winreg.QueryValueEx(key, "")
                    except FileNotFoundError:
                        value = None
                    if value == progid:
                        winreg.DeleteValue(key, "")
            except FileNotFoundError:
                pass
            except OSError:
                pass
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, rf"{classes}\{ext}\OpenWithProgids",
                                    0, winreg.KEY_READ | winreg.KEY_WRITE) as key:
                    winreg.DeleteValue(key, progid)
            except (FileNotFoundError, OSError):
                pass

    for ext in CONTEXT_MENU_EXTS:
        delete_tree(winreg.HKEY_CURRENT_USER,
                    rf"{classes}\SystemFileAssociations\{ext}\shell\{VERB_KEY}")

    _notify_shell()
    print(f"Removed: {', '.join(removed) if removed else 'nothing was registered'}")
    return 0


def _notify_shell() -> None:
    """Tell Explorer that association data changed."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        SHCNE_ASSOCCHANGED, SHCNF_IDLIST = 0x08000000, 0x0000
        ctypes.windll.shell32.SHChangeNotify(SHCNE_ASSOCCHANGED, SHCNF_IDLIST, None, None)
    except Exception:
        pass


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

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
    p.add_argument("--version", action="version", version=f"{APP_NAME} {__version__}")
    return p


def _warm_renderers() -> None:
    """Import the markdown stack and build the highlight CSS, off the main thread."""
    try:
        markdown_render._markdown_module()
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


if __name__ == "__main__":
    sys.exit(main())
