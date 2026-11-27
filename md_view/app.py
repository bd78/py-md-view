"""Viewer and API bridge for pywebview."""

from __future__ import annotations

import os
import re
import threading
import time
from pathlib import Path

from . import config, documents, links, mermaid_assets, page, trees
from .config import APP_NAME, DEFAULT_STYLE, FONTS, STYLE_BG, STYLES, VIEWABLE_EXTS


def _drop_stale_bridge_replies() -> None:
    """Silence pywebview's error for a bridge reply whose page is gone.

    Most bridge calls change what is on screen -- open, switch or close a tab --
    so they end in ``load_url``. pywebview then hands back the call's return
    value through a callback on the page that made the call, but only after
    waiting for the *new* page to load, which never registered that callback.
    Each such call therefore raised ``JavascriptException`` in a worker thread
    and printed a traceback. Nothing is lost by dropping it: the page that
    wanted the reply is gone, and ``call()`` in the page ignores replies
    anyway. Every other thread exception goes to the previous hook.
    """
    previous = threading.excepthook

    def hook(args: threading.ExceptHookArgs) -> None:
        exc = args.exc_value
        # Matched by name: webview is imported lazily, not at module level.
        if (type(exc).__name__ == "JavascriptException"
                and "_returnValuesCallbacks" in str(exc)):
            return
        previous(args)

    threading.excepthook = hook


class Tab:
    """One open document, with its own history and scroll position."""

    __slots__ = ("path", "history", "forward", "scroll")

    def __init__(self, path: Path | None):
        self.path = path
        self.history: list[Path] = []
        self.forward: list[Path] = []
        self.scroll = 0.0

    @property
    def title(self) -> str:
        return self.path.name if self.path else "Start"

    def describe(self, stale: bool = False) -> dict:
        return {
            "title": self.title,
            "path": str(self.path) if self.path else "",
            "stale": stale,
        }


class Viewer:
    """Owns the window, the open tabs and the file watcher.

    Threading. Navigation is triggered from three places: the UI thread, the JS
    bridge (a link click, a tab click) and the file watcher. Two locks keep that
    safe, and the order between them matters:

    ``_js``  serialises ``evaluate_js``.
    ``_nav`` guards tab state, page staging and window navigation. Everything
             it protects is fast and never waits on the page.

    ``_js`` is always taken *and released* before ``_nav``. Holding ``_nav``
    across an ``evaluate_js`` deadlocks: the result is delivered on the bridge
    thread, and that thread would itself be blocked waiting for ``_nav``.
    """

    def __init__(self, paths: list[Path] | Path | None = None, *, style: str, zoom: float,
                 watch: bool = True, mermaid: bool = True, debug: bool = False,
                 font: str = "system"):
        import tempfile
        import webview  # imported here so --register works without a GUI stack

        self.webview = webview
        self.prefs = config.load_prefs()
        self.style = style
        self.font = font if font in FONTS else "system"
        self.csv_align = bool(self.prefs.get("csv_align", False))
        # Kept for the session only: a repaint should not lose what you
        # were searching for, but it does not belong in prefs.
        self.find_query = ""
        self.zoom = zoom
        self.fit = bool(self.prefs.get("fit", True))
        self.watch_enabled = watch
        self.mermaid_enabled = mermaid
        self.debug = debug

        if isinstance(paths, (Path, str)):
            paths = [Path(paths)]          # a single document is the common case
        opening = [p for p in (paths or []) if p is not None]
        self.tabs: list[Tab] = [Tab(self._canon(p)) for p in opening] or [Tab(None)]
        self.active = 0

        self._tmpdir = Path(tempfile.mkdtemp(prefix="mdview-"))
        self._counter = 0
        self._bridge_key = None
        self._nav = threading.RLock()
        self._js = threading.RLock()
        self._mtimes: dict[Path, float] = {}
        self._stale: set[Path] = set()
        self._capture_failures = 0
        # Mermaid arrives in the background: the page that failed to get it from
        # the CDN is repainted once, when the cache fills (or at once if it has).
        self._mermaid_lock = threading.Lock()
        self._mermaid_missing = False
        self._mermaid_repainted = False

        # Sidebar state lives here, not in the page: every navigation rebuilds
        # the document, and expanded folders must survive that.
        self.sidebar_visible = bool(self.prefs.get("sidebar", True))
        self.sidebar_width = int(self.prefs.get("sidebar_width") or 264)
        self.docs_height = int(self.prefs.get("docs_height") or 220)
        self.panes = dict(self.prefs.get("panes") or {})
        self.doc_collapsed = self._canon_set(self.prefs.get("doc_collapsed"))
        # Node keys, not paths: entries saved by an older version carry no
        # root and are dropped rather than guessed at.
        self.expanded = {k for k in (self.prefs.get("expanded") or [])
                         if isinstance(k, str) and trees.KEY_SEP in k}
        # Pinned for the session: see trees.filesystem_roots. Opening a file must not
        # move the tree out from under the reader.
        self.fs_anchor = trees.documents_anchor([t.path for t in self.tabs if t.path])
        if self.fs_anchor is not None:
            # start where the documents live
            self.expanded.add(trees.node_key("anchor", self.fs_anchor))
        self._stop = threading.Event()
        self._window = None
        self._server = None

    # -- helpers ----------------------------------------------------------- #

    @staticmethod
    def _canon(path: Path | None) -> Path | None:
        """Canonical form, so the same file always compares equal.

        Paths arrive from the command line, from links, from another instance
        and from the file dialog, each with its own spelling (short names,
        mixed case, `..`).
        """
        if path is None:
            return None
        try:
            return path.resolve()
        except OSError:
            return path

    @staticmethod
    def _safe_mtime(path: Path | None) -> float | None:
        try:
            return path.stat().st_mtime if path else None
        except OSError:
            return None

    @property
    def tab(self) -> Tab:
        return self.tabs[self.active]

    @property
    def current(self) -> Path | None:
        return self.tab.path

    def _title(self, path: Path | None) -> str:
        extra = f" [{len(self.tabs)}]" if len(self.tabs) > 1 else ""
        return f"{path.name} - {APP_NAME}{extra}" if path else f"{APP_NAME}{extra}"

    def _stage(self, html_text: str) -> str:
        """Write HTML to a fresh temp file and return its file:// URL.

        A new name each time: navigating to the URL that is already loaded
        produces no navigation event, which would strand ``evaluate_js``.
        """
        import secrets

        self._counter += 1
        f = self._tmpdir / f"view-{self._counter:04d}.html"
        f.write_text(html_text, "utf-8")
        for old in self._tmpdir.glob("view-*.html"):
            try:
                if old != f and self._counter - int(old.stem.split("-")[1]) > 2:
                    old.unlink(missing_ok=True)
            except (ValueError, OSError):
                pass
        # Only the navigation initiated by Python carries the key. A file URL
        # fragment is omitted from referrers and never written into the HTML.
        # Repaints rotate it so previously staged pages lose access.
        self._bridge_key = secrets.token_urlsafe(32)
        return f"{f.as_uri()}#{self._bridge_key}"

    # -- page building ----------------------------------------------------- #

    def _tab_dicts(self) -> list[dict]:
        return [t.describe(stale=t.path is not None and t.path in self._stale)
                for t in self.tabs]

    def _sidebar(self) -> dict:
        """Everything the two trees need, resolved at page-build time."""
        try:
            files = trees.build_fs_tree(self.fs_anchor, self.expanded)
        except Exception:
            files = []          # an unreadable drive must not blank the page
        return {
            "visible": self.sidebar_visible,
            "width": self.sidebar_width,
            "docs_height": self.docs_height,
            "panes": self.panes,
            "docs": trees.build_doc_tree(self.tabs, self.active, self._stale,
                                   self.doc_collapsed),
            "files": files,
        }

    def _page_for(self, tab: Tab, scroll: float) -> str:
        tabs, active = self._tab_dicts(), self.active
        side = self._sidebar()
        path = tab.path
        if path is None:
            return page.render_welcome(self.style, tabs, active, side, self.font)
        try:
            if not path.exists():
                return page.render_error("File not found", str(path), self.style, tabs, active,
                                    can_go_back=bool(tab.history), sidebar=side,
                                    font=self.font)
            if path.is_dir():
                return page.render_error("That is a folder", str(path), self.style, tabs, active,
                                    can_go_back=bool(tab.history), sidebar=side,
                                    font=self.font)
            html_text = page.render_document(
                path, style=self.style, zoom=self.zoom, fit=self.fit,
                scroll=scroll, can_go_back=bool(tab.history),
                tabs=tabs, active_tab=active, sidebar=side, font=self.font,
                csv_align=self.csv_align, find_query=self.find_query,
            )
            if not self.mermaid_enabled:
                html_text = html_text.replace("__mdv_mermaidReady()", "void 0")
            return html_text
        except OSError as exc:
            return page.render_error("Cannot read this file", str(exc), self.style, tabs, active,
                                sidebar=side, font=self.font)
        except Exception as exc:  # a bad document must not take the viewer down
            if self.debug:
                import traceback
                traceback.print_exc()
            return page.render_error("Failed to render", f"{type(exc).__name__}: {exc}",
                                self.style, tabs, active, sidebar=side, font=self.font)

    def _paint(self, *, scroll: float | None = None) -> str:
        """Render the active tab into the window. Caller must hold _nav."""
        tab = self.tab
        if scroll is None:
            scroll = tab.scroll
        if tab.path is not None:
            mtime = self._safe_mtime(tab.path)
            if mtime is not None:
                self._mtimes[tab.path] = mtime
            self._stale.discard(tab.path)
        url = self._stage(self._page_for(tab, scroll))
        if self._window is not None:
            self._window.set_title(self._title(tab.path))
            self._window.load_url(url)
        return url

    def _capture_scroll(self) -> None:
        """Remember where the visible tab is scrolled to. Best effort only.

        pywebview waits on ``evaluate_js`` with no timeout, so a call that races
        a navigation can be stranded for good. Losing a scroll offset is
        cosmetic; a frozen window is not, so this gives up quickly and, after a
        few failures, stops asking altogether. Never holds ``_nav``.
        """
        window = self._window
        if window is None or self._capture_failures >= 3:
            return
        if not self._js.acquire(blocking=False):
            return  # a capture is already in flight; one sample is enough
        try:
            box: dict[str, object] = {}

            def ask() -> None:
                try:
                    box["value"] = window.evaluate_js(
                        "window.__mdv_scroll && window.__mdv_scroll()"
                    )
                except Exception:
                    box["value"] = None

            worker = threading.Thread(target=ask, daemon=True)
            worker.start()
            worker.join(1.5)
            if worker.is_alive():
                self._capture_failures += 1
                return
            self._capture_failures = 0
            try:
                self.tab.scroll = float(box.get("value") or 0.0)
            except (TypeError, ValueError):
                pass
        finally:
            self._js.release()

    # -- tabs -------------------------------------------------------------- #

    def open_tab(self, path: Path | None, *, focus: bool = True) -> int:
        """Open a document in a new tab, or focus the tab that already has it."""
        path = self._canon(path)
        self._capture_scroll()
        with self._nav:
            for index, tab in enumerate(self.tabs):
                if tab.path == path and path is not None:
                    self.active = index
                    self._paint()
                    return index
            # An untouched Start tab is a placeholder: reuse it.
            if len(self.tabs) == 1 and self.tabs[0].path is None:
                self.tabs[0] = Tab(path)
                self.active = 0
            else:
                self.tabs.insert(self.active + 1, Tab(path))
                if focus:
                    self.active += 1
            self._paint()
            return self.active

    def select_tab(self, index: int) -> None:
        self._capture_scroll()
        with self._nav:
            if not 0 <= index < len(self.tabs) or index == self.active:
                return
            self.active = index
            self._paint()

    def close_tab(self, index: int = -1) -> None:
        self._capture_scroll()
        with self._nav:
            if index < 0:
                index = self.active
            if not 0 <= index < len(self.tabs):
                return
            if len(self.tabs) == 1:
                # Last tab: close the window, the way a browser would.
                if self._window is not None:
                    self._window.destroy()
                return
            gone = self.tabs.pop(index)
            if gone.path is not None and not any(t.path == gone.path for t in self.tabs):
                self._mtimes.pop(gone.path, None)
                self._stale.discard(gone.path)
            if self.active > index or self.active >= len(self.tabs):
                self.active = max(0, self.active - 1)
            self._paint()

    def next_tab(self) -> None:
        self.select_tab((self.active + 1) % len(self.tabs))

    def prev_tab(self) -> None:
        self.select_tab((self.active - 1) % len(self.tabs))

    # -- navigation within a tab ------------------------------------------- #

    def show(self, path: Path | None, *, scroll: float = 0.0, record: bool = True):
        """Point the active tab at `path`."""
        path = self._canon(path)
        with self._nav:
            tab = self.tab
            if record and tab.path is not None and tab.path != path:
                tab.history.append(tab.path)
                tab.forward.clear()
            tab.path = path
            tab.scroll = scroll
            return self._paint(scroll=scroll)

    def go_back(self) -> None:
        with self._nav:
            tab = self.tab
            if not tab.history:
                return
            target = tab.history.pop()
            if tab.path:
                tab.forward.append(tab.path)
            tab.path = target
            tab.scroll = 0.0
            self._paint(scroll=0.0)

    def go_forward(self) -> None:
        with self._nav:
            tab = self.tab
            if not tab.forward:
                return
            target = tab.forward.pop()
            if tab.path:
                tab.history.append(tab.path)
            tab.path = target
            tab.scroll = 0.0
            self._paint(scroll=0.0)

    def refresh(self) -> None:
        """Rebuild the active tab from disk, keeping the scroll position."""
        self._capture_scroll()
        with self._nav:
            if self.tab.path is not None:
                documents.invalidate_document(self.tab.path)
            self._paint()

    def mermaid_missing(self) -> None:
        """The page found no mermaid.js. Repaint once the cache has it."""
        with self._mermaid_lock:
            if self._mermaid_repainted:
                return
            if mermaid_assets.find_mermaid() is None:
                self._mermaid_missing = True
                return
            self._mermaid_repainted = True
        self.refresh()

    def mermaid_arrived(self) -> None:
        """The background download finished: repaint only if a page needed it."""
        with self._mermaid_lock:
            if not (self._mermaid_missing and mermaid_assets.find_mermaid()) or self._mermaid_repainted:
                return
            self._mermaid_missing = False
            self._mermaid_repainted = True
        self.refresh()

    def open_path(self, raw: str, *, new_tab: bool = False) -> bool:
        """Open a link target: viewable files in-app, anything else via the OS."""
        base = self.current.parent if self.current else Path.cwd()
        path = links._path_from_href(raw, base)
        if path is None:
            return False
        # Before is_dir() or any read: a document must not make this PC sign in
        # to another computer just because the reader clicked a link.
        if links._is_network_path(path) and not (self._window is not None and self._window.create_confirmation_dialog(
                APP_NAME, f"This link reads from another computer on the network.\n"
                          f"Windows may send your sign-in to it.\n\n{path}\n\nOpen it?")):
            return False
        # On macOS a folder with an extension may be a bundle (.app, .prefPane)
        # that `open` launches, so it is asked about below like a program.
        if path.is_dir() and not (config._IS_MAC and path.suffix):
            links._os_open(path)
            return False
        if path.suffix.lower() in VIEWABLE_EXTS:
            if new_tab:
                self.open_tab(path)
            else:
                self.show(path)
            return True
        # Asked every time, as a browser does for a download: the link may be
        # a program, and the request may come from a page rather than a click.
        if self._window is not None and self._window.create_confirmation_dialog(
                APP_NAME, f"md-view cannot show {path.name}.\n\n"
                          f"Open it with its default app?\n\n{path}"):
            links._os_open(path)
        return False

    def _raise(self) -> None:
        """Bring the window forward without touching its geometry.

        Only for files arriving from *another process*; opening a tab from
        inside the window must never disturb it.

        Deliberately not window.restore(): that sets WindowState to Normal,
        which un-maximises. show() is Show() + Activate(), which leaves the
        window state, size and position exactly as the user left them.
        """
        if self._window is None:
            return
        try:
            self._window.show()
        except Exception:
            pass

    # -- file watching ----------------------------------------------------- #

    def _watch_loop(self) -> None:
        """Reload the visible tab when its file changes; flag the others."""
        while not self._stop.wait(0.7):
            # Under the lock: close_tab pops a tab one step before it fixes
            # self.active, and reading self.current in between raised
            # IndexError here, which ended the watcher for the session.
            with self._nav:
                watched = [t.path for t in self.tabs if t.path is not None]
                active_path = self.current
            for path in dict.fromkeys(watched):
                known = self._mtimes.get(path)
                if known is None:
                    continue
                now = self._safe_mtime(path)
                if now is None or now == known:
                    continue
                time.sleep(0.15)  # let a slow writer finish
                if self._safe_mtime(path) != now:
                    continue
                self._mtimes[path] = now
                documents.invalidate_document(path)
                if path == active_path:
                    try:
                        self.refresh()
                    except Exception:
                        pass
                else:
                    # Mark it and repaint so the tab shows its dot.
                    self._stale.add(path)
                    with self._nav:
                        try:
                            self._paint()
                        except Exception:
                            pass

    # -- lifecycle --------------------------------------------------------- #

    def run(self) -> None:
        import shutil
        from hmac import compare_digest

        api = Api(self)
        # Every public Api method, read from the class so that adding or
        # deleting one there can never leave this table naming a missing method.
        actions = {name: getattr(api, name) for name in dir(api)
                   if not name.startswith("_") and callable(getattr(api, name))}

        def dispatch(key, action, args):
            current_key = self._bridge_key
            if (current_key is None or not isinstance(key, str) or not key.isascii()
                    or not compare_digest(key, current_key)
                    or not isinstance(action, str) or not isinstance(args, list)):
                return None
            handler = actions.get(action)
            return handler(*args) if handler is not None else None

        with self._nav:
            start_url = self._stage(self._page_for(self.tab, 0.0))
            if self.tab.path is not None:
                mtime = self._safe_mtime(self.tab.path)
                if mtime is not None:
                    self._mtimes[self.tab.path] = mtime
        bg = STYLE_BG.get(self.style, "#ffffff")

        # pywebview sends a new-window request (target=_blank, middle-click) to webbrowser.open, which on
        # Windows is os.startfile: a document link to file:///...exe would run with no question. Keep it
        # in the window instead; links md-view itself opens go through open_external, which asks.
        self.webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = False
        self._window = self.webview.create_window(
            self._title(self.current),
            url=start_url,
            width=1100, height=820, min_size=(420, 320),
            background_color=bg,
            text_select=True,
            zoomable=False,          # we manage zoom ourselves so the chrome stays fixed
            easy_drag=False,
        )
        api._window = self._window
        # Use an explicit function rather than giving pywebview a traversable
        # js_api object. The dispatcher checks the key on every call.
        self._window.expose(dispatch)

        def on_start():
            if self.watch_enabled:
                threading.Thread(target=self._watch_loop, daemon=True).start()

        _drop_stale_bridge_replies()
        try:
            # Private mode keeps each process on its own ephemeral profile, so
            # a second launch never contends for a shared WebView2 user-data
            # folder. Preferences live in prefs.json on the Python side.
            self.webview.start(on_start, debug=self.debug)
        finally:
            self._stop.set()
            if self._server is not None:
                self._server.close()
            self._persist()
            shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _persist(self) -> None:
        self.prefs.update({
            "style": self.style, "style_default": DEFAULT_STYLE,
            "zoom": round(self.zoom, 4), "fit": self.fit,
            "font": self.font, "csv_align": self.csv_align,
            "sidebar": self.sidebar_visible, "sidebar_width": self.sidebar_width,
            "docs_height": self.docs_height, "panes": self.panes,
            # Keep the list bounded: an unbounded set would grow forever.
            "expanded": sorted(list(self.expanded)[:400]),
            "doc_collapsed": sorted(str(p) for p in list(self.doc_collapsed)[:200]),
        })
        config.save_prefs(self.prefs)

    # -- sidebar ----------------------------------------------------------- #

    def set_expanded(self, keys: list[str]) -> None:
        """Replace the expanded set from the page.

        These are node keys the page got from us, so they round-trip exactly;
        no normalising is needed or wanted.
        """
        self.expanded = {k for k in (keys or []) if isinstance(k, str) and trees.KEY_SEP in k}
        self._persist()

    @classmethod
    def _canon_set(cls, paths) -> set[Path]:
        """Canonical paths, so a folder compares equal however it was spelled."""
        fresh: set[Path] = set()
        for item in paths or []:
            if not item:
                continue
            try:
                canon = cls._canon(Path(item))
            except (TypeError, ValueError, OSError):
                continue
            if canon is not None:
                fresh.add(canon)
        return fresh

    def set_doc_collapsed(self, paths: list[str]) -> None:
        """Replace the set of folders collapsed in the open-documents tree."""
        self.doc_collapsed = self._canon_set(paths)
        self._persist()

    def open_from_tree(self, raw: str) -> bool:
        """Open a file picked in the computer tree, always in its own tab."""
        try:
            path = Path(raw)
        except (TypeError, ValueError):
            return False
        if path.is_dir():
            return False        # folders are expanded by the tree, not opened
        if not path.exists():
            return False
        if path.suffix.lower() in VIEWABLE_EXTS:
            self.open_tab(path)
            return True
        return False            # the tree lists only viewable files

    def toggle_csv_align(self) -> bool:
        """Alignment changes the rendered text, so the tab is rebuilt."""
        self.csv_align = not self.csv_align
        self._persist()
        self._capture_scroll()
        with self._nav:
            self._paint()
        return self.csv_align

    def reveal_current(self) -> bool:
        """Expand down to the active document under every root holding it."""
        path = self.current
        if path is None:
            return False
        for root in trees.filesystem_roots(self.fs_anchor):
            root_path = Path(root["path"])
            if not trees._is_under(path, root_path):
                continue
            cursor = path.parent
            while True:
                self.expanded.add(trees.node_key(root["root"], cursor))
                if trees._same_path(cursor, root_path) or cursor == cursor.parent:
                    break
                cursor = cursor.parent
        self._persist()
        with self._nav:
            self._paint()
        return True


class Api:
    """Viewer actions available through the authenticated dispatcher.

    These run on the JS bridge thread. None of them may block on the page.
    """

    def __init__(self, viewer: Viewer):
        self._viewer = viewer
        self._window = None

    # navigation
    def go_back(self):
        self._viewer.go_back()

    def go_forward(self):
        self._viewer.go_forward()

    def refresh(self):
        self._viewer.refresh()

    def mermaid_missing(self):
        self._viewer.mermaid_missing()

    def open_path(self, href: str):
        return self._viewer.open_path(href)

    def open_external(self, url: str):
        if re.match(r"^(https?|ftp|mailto):", url, re.IGNORECASE):
            import webbrowser
            webbrowser.open(url)

    # tabs
    def select_tab(self, index: int):
        try:
            self._viewer.select_tab(int(index))
        except (TypeError, ValueError):
            pass

    def close_tab(self, index: int = -1):
        try:
            self._viewer.close_tab(int(index))
        except (TypeError, ValueError):
            pass

    def next_tab(self):
        self._viewer.next_tab()

    def prev_tab(self):
        self._viewer.prev_tab()

    def new_tab(self):
        return self.pick_file(new_tab=True)

    def pick_file(self, new_tab: bool = False):
        if self._window is None:
            return None
        types = (
            "Viewable files (*.md;*.markdown;*.mmd;*.mermaid;*.svg;*.png;*.jpg;*.jpeg;*.gif;*.webp;*.bmp)",
            "Markdown (*.md;*.markdown;*.mdown;*.mkd)",
            "Mermaid (*.mmd;*.mermaid)",
            "Images (*.png;*.jpg;*.jpeg;*.gif;*.webp;*.bmp;*.ico;*.svg)",
            "All files (*.*)",
        )
        current = self._viewer.current
        start = str(current.parent) if current else ""
        result = self._window.create_file_dialog(
            self._viewer.webview.OPEN_DIALOG, directory=start,
            allow_multiple=True, file_types=types,
        )
        if not result:
            return None
        chosen = [Path(r) for r in result]
        if new_tab or len(chosen) > 1 or self._viewer.current is not None:
            for path in chosen:
                self._viewer.open_tab(path)
        else:
            self._viewer.show(chosen[0])
        return str(chosen[0])

    # sidebar trees
    def list_dir(self, path: str):
        """Children of a folder, for lazy expansion. Never raises into JS."""
        try:
            target = Path(path)
            if not target.is_dir():
                return {"path": path, "entries": [], "more": 0, "denied": True}
            entries, more = trees.dir_entries(target)
            return {"path": path, "entries": entries, "more": more, "denied": False}
        except (OSError, ValueError):
            return {"path": path, "entries": [], "more": 0, "denied": True}

    def set_expanded(self, paths: list):
        self._viewer.set_expanded(list(paths or []))
        return True

    def set_doc_collapsed(self, paths: list):
        self._viewer.set_doc_collapsed(list(paths or []))
        return True

    def open_from_tree(self, path: str):
        return self._viewer.open_from_tree(path)

    def set_sidebar(self, visible: bool = True, width: int = 0, panes: dict | None = None,
                    docs_height: int = 0):
        viewer = self._viewer
        viewer.sidebar_visible = bool(visible)
        try:
            if width:
                viewer.sidebar_width = max(160, min(640, int(width)))
        except (TypeError, ValueError):
            pass
        try:
            if docs_height:
                viewer.docs_height = max(60, min(1200, int(docs_height)))
        except (TypeError, ValueError):
            pass
        if isinstance(panes, dict):
            viewer.panes = {k: bool(v) for k, v in panes.items()}
        viewer._persist()
        return True

    def reveal_active(self):
        """Expand the computer tree down to the document on screen."""
        return self._viewer.reveal_current()

    # window
    def toggle_fullscreen(self):
        if self._window is not None:
            self._window.toggle_fullscreen()

    def set_find_query(self, query: str):
        """Remember the search text so a repaint can put it back."""
        try:
            self._viewer.find_query = str(query or "")[:200]
        except (TypeError, ValueError):
            self._viewer.find_query = ""
        return True

    def set_font(self, name: str):
        """Change the body typeface. CSS-only, so no repaint is needed."""
        if name not in FONTS:
            return False
        self._viewer.font = name
        self._viewer._persist()
        return True

    def toggle_csv_align(self):
        """Flip column alignment and rebuild the view."""
        return self._viewer.toggle_csv_align()

    # preferences
    def save_view_prefs(self, state: dict):
        try:
            if "zoom" in state:
                self._viewer.zoom = float(state["zoom"])
            if state.get("style") in STYLES:
                self._viewer.style = state["style"]
            if "fit" in state:
                self._viewer.fit = bool(state["fit"])
        except (TypeError, ValueError):
            return False
        self._viewer._persist()
        return True
