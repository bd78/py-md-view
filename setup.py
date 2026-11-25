#!/usr/bin/env python3
"""Packaging for md-view: `pip install .` adds md-view.py to Scripts.

Setting up needs no setuptools at all; these are md-view.py flags:
    python -m pip install -r requirements.txt
    python md-view.py --fetch-assets      # cache mermaid.js for offline diagrams
    python md-view.py --register          # associate .md / .mmd (Windows)

Author: bd78 (https://github.com/bd78)
"""

from __future__ import annotations

from pathlib import Path

from setuptools import setup

HERE = Path(__file__).resolve().parent


def read(name: str, default: str = "") -> str:
    p = HERE / name
    return p.read_text("utf-8") if p.is_file() else default


def version() -> str:
    for line in read("md-view.py").splitlines():
        if line.startswith("__version__"):
            return line.split("=", 1)[1].strip().strip("\"'")
    return "0.0.0"


def requirements() -> list[str]:
    """requirements.txt is the one dependency list; its platform markers carry over."""
    return [line.strip() for line in read("requirements.txt").splitlines()
            if line.strip() and not line.lstrip().startswith("#")]


setup(
    name="md-view",
    version=version(),
    description="Lightweight native viewer for Markdown, Mermaid, SVG and images",
    long_description=read("README.md"),
    long_description_content_type="text/markdown",
    author="Bruno D.",
    license="MIT",
    python_requires=">=3.9",
    install_requires=requirements(),
    # md-view.py is a script, not an importable module (the hyphen is deliberate:
    # it reads well on a command line and in a registry command string).
    scripts=["md-view.py"],
    classifiers=[
        "Development Status :: 4 - Beta",
        "Environment :: Win32 (MS Windows)",
        "Intended Audience :: Developers",
        "Operating System :: Microsoft :: Windows",
        "Operating System :: POSIX :: Linux",
        "Operating System :: MacOS :: MacOS X",
        "Programming Language :: Python :: 3",
        "Topic :: Text Processing :: Markup :: Markdown",
        "Topic :: Utilities",
    ],
)
