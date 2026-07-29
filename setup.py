#!/usr/bin/env python3
"""Requirements setup for md-view.

Typical use:
    python setup.py develop_local     # install deps into the current interpreter
    python setup.py fetch_assets      # cache mermaid.js for offline diagrams
    pip install .                     # regular install (adds md-view.py to Scripts)
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from setuptools import Command, setup

HERE = Path(__file__).resolve().parent


def read(name: str, default: str = "") -> str:
    p = HERE / name
    return p.read_text("utf-8") if p.is_file() else default


def version() -> str:
    for line in read("md-view.py").splitlines():
        if line.startswith("__version__"):
            return line.split("=", 1)[1].strip().strip("\"'")
    return "0.0.0"


# --------------------------------------------------------------------------- #
# Dependencies
# --------------------------------------------------------------------------- #
# pywebview draws the window with the platform's own web view -- WebView2 on
# Windows, WebKit on macOS, WebKitGTK on Linux -- so there is no bundled
# browser engine to ship or start up.

INSTALL_REQUIRES = [
    "pywebview>=5.0",
    "markdown>=3.5",
    "pygments>=2.17",
]

EXTRAS = {
    # pywebview's Windows backend talks to WebView2 through .NET.
    ":sys_platform == 'win32'": ["pythonnet>=3.0"],
    # Linux needs the GTK bindings for WebKitGTK.
    ":sys_platform == 'linux'": ["pywebview[gtk]>=5.0"],
    "dev": ["pytest>=8.0"],
}


# --------------------------------------------------------------------------- #
# Custom commands
# --------------------------------------------------------------------------- #

class FetchAssets(Command):
    """Download mermaid.min.js so diagrams render without a network."""

    description = "download mermaid.js into the per-user asset cache"
    user_options = [
        ("force", "f", "re-download even if a cached copy exists"),
        ("vendor", None, "save into ./assets next to md-view.py instead of the user cache"),
    ]

    def initialize_options(self):
        self.force = False
        self.vendor = False

    def finalize_options(self):
        pass

    def run(self):
        sys.path.insert(0, str(HERE))
        import importlib.util

        spec = importlib.util.spec_from_file_location("mdview_main", HERE / "md-view.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        if self.vendor:
            import urllib.request

            target = HERE / "assets" / "mermaid.min.js"
            target.parent.mkdir(parents=True, exist_ok=True)
            print(f"Downloading {module.MERMAID_CDN} -> {target}")
            with urllib.request.urlopen(module.MERMAID_CDN, timeout=120) as resp:
                target.write_bytes(resp.read())
            print(f"Vendored {target} ({target.stat().st_size / 1e6:.1f} MB)")
            return

        if module.fetch_mermaid(force=bool(self.force)) is None:
            raise SystemExit("mermaid.js download failed")


class DevelopLocal(Command):
    """pip-install the runtime dependencies into the running interpreter."""

    description = "install runtime dependencies with pip"
    user_options = [("upgrade", "U", "upgrade already-installed packages")]

    def initialize_options(self):
        self.upgrade = False

    def finalize_options(self):
        pass

    def run(self):
        requirements = list(INSTALL_REQUIRES)
        if sys.platform == "win32":
            requirements.append("pythonnet>=3.0")
        elif sys.platform == "linux":
            requirements.append("pywebview[gtk]>=5.0")
        cmd = [sys.executable, "-m", "pip", "install"]
        if self.upgrade:
            cmd.append("--upgrade")
        cmd += requirements
        print(" ".join(cmd))
        subprocess.check_call(cmd)


class Register(Command):
    """Associate .md / .mmd with the viewer (Windows)."""

    description = "register file associations for .md and .mmd"
    user_options = [("undo", None, "remove the associations instead")]

    def initialize_options(self):
        self.undo = False

    def finalize_options(self):
        pass

    def run(self):
        flag = "--unregister" if self.undo else "--register"
        subprocess.check_call([sys.executable, str(HERE / "md-view.py"), flag])


setup(
    name="md-view",
    version=version(),
    description="Lightweight native viewer for Markdown, Mermaid, SVG and images",
    long_description=read("README.md"),
    long_description_content_type="text/markdown",
    author="Bruno Dujardin",
    license="MIT",
    python_requires=">=3.9",
    install_requires=INSTALL_REQUIRES,
    extras_require=EXTRAS,
    # md-view.py is a script, not an importable module (the hyphen is deliberate:
    # it reads well on a command line and in a registry command string).
    scripts=["md-view.py"],
    cmdclass={
        "fetch_assets": FetchAssets,
        "develop_local": DevelopLocal,
        "register": Register,
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Environment :: Win32 (MS Windows)",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Operating System :: Microsoft :: Windows",
        "Operating System :: POSIX :: Linux",
        "Operating System :: MacOS :: MacOS X",
        "Programming Language :: Python :: 3",
        "Topic :: Text Processing :: Markup :: Markdown",
        "Topic :: Utilities",
    ],
)
