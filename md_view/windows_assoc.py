"""Windows file associations and registry registration."""

from __future__ import annotations

import sys
from pathlib import Path

from . import config
from .config import APP_NAME, IMAGE_EXTS, MARKDOWN_EXTS, MERMAID_EXTS

PROGIDS = {
    "markdown": ("md-view.markdown", "Markdown Document", sorted(MARKDOWN_EXTS)),
    "mermaid": ("md-view.mermaid", "Mermaid Diagram", sorted(MERMAID_EXTS)),
}
CONTEXT_MENU_EXTS = sorted(MARKDOWN_EXTS | MERMAID_EXTS | IMAGE_EXTS)
VERB_KEY = "md-view.open"


def _launch_command() -> tuple[str, str]:
    """Return (command, icon) for the registry, preferring a console-free launcher."""
    script = config.LAUNCHER if hasattr(config, "LAUNCHER") and config.LAUNCHER else Path(__file__).resolve().parent.parent / "md-view.py"
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
