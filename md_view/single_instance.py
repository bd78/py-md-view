"""Single instance: hand new files to the window that is already open."""

from __future__ import annotations

import json
import os
import socket
import sys
import threading
from pathlib import Path

from . import config
from .config import APP_NAME


class InstanceServer:
    """A loopback listener that accepts paths from later launches."""

    def __init__(self, viewer):
        import secrets

        self.viewer = viewer
        self.token = secrets.token_hex(16)
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(8)
        self.port = self._sock.getsockname()[1]
        self._closed = False
        self._record()
        threading.Thread(target=self._serve, daemon=True).start()

    def _record(self) -> None:
        payload = {"port": self.port, "token": self.token, "pid": os.getpid()}
        try:
            instance_file().write_text(json.dumps(payload), "utf-8")
        except OSError:
            pass

    def _serve(self) -> None:
        while not self._closed:
            try:
                conn, _ = self._sock.accept()
            except OSError:
                return
            with conn:
                try:
                    conn.settimeout(5)
                    raw = conn.recv(65536).decode("utf-8", errors="replace")
                    message = json.loads(raw or "{}")
                    # The token stops anything else on the machine from
                    # driving this window.
                    if message.get("token") != self.token:
                        conn.sendall(b"denied")
                        continue
                    paths = [Path(item) for item in message.get("paths") or []]
                    paths = [p for p in paths if p.exists()]
                    # Answer before opening: opening can outlast the sender's
                    # timeout, and a sender that gives up opens a second window.
                    conn.sendall(b"ok" if paths else b"empty")
                    for path in paths:
                        try:
                            self.viewer.open_tab(path)
                        except OSError as exc:      # one bad file must not drop the rest
                            print(f"{APP_NAME}: could not open {path}: {exc}", file=sys.stderr)
                    if paths:
                        # Only a hand-off from another process brings the
                        # window forward; in-app opens leave it alone.
                        self.viewer._raise()
                except (OSError, ValueError, TypeError):
                    continue

    def close(self) -> None:
        self._closed = True
        try:
            self._sock.close()
        except OSError:
            pass
        try:
            current = json.loads(instance_file().read_text("utf-8"))
            if current.get("pid") == os.getpid():
                instance_file().unlink(missing_ok=True)
        except (OSError, ValueError):
            pass


def instance_file() -> Path:
    return config.data_dir() / "instance.json"


def instance_lock():
    """Take the per-user lock that marks the window owner; None if it is held.

    Launches that start together (several files opened at once from Explorer)
    would all find no running window; the lock lets exactly one become it.
    The OS drops the lock when its process exits, so a crash never leaves it
    stale. The returned handle must stay referenced while the window is open.
    """
    import errno

    try:
        handle = open(config.data_dir() / "instance.lock", "a+b")
    except OSError:
        return True     # no lock file possible: every launch may own a window, as before
    try:
        handle.seek(0)
        if sys.platform == "win32":
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return handle
    except OSError as exc:
        handle.close()
        # Only "someone else holds it" means another viewer owns the window.
        # msvcrt reports that as EACCES (EDEADLOCK from the blocking form).
        if isinstance(exc, BlockingIOError) or (
                sys.platform == "win32" and exc.errno in (errno.EACCES, errno.EDEADLK)):
            return None
        # Any other failure (ENOLCK, ...) would make every launch wait for an
        # owner that never comes; open a window without the lock instead.
        print(f"{APP_NAME}: cannot take the instance lock ({exc})", file=sys.stderr)
        return True


def hand_off(paths: list[Path], timeout: float = 2.0) -> bool:
    """Ask a running viewer to open these paths. True when it accepted."""
    try:
        info = json.loads(instance_file().read_text("utf-8"))
        port, token = int(info["port"]), str(info["token"])
    except (OSError, ValueError, KeyError, TypeError):
        return False
    payload = json.dumps({"token": token, "paths": [str(p) for p in paths]})
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout) as sock:
            sock.settimeout(timeout)
            sock.sendall(payload.encode("utf-8"))
            return sock.recv(16).startswith(b"ok")
    except OSError:
        # Stale record: the previous instance is gone.
        return False
