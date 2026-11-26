# Spec: Split md-view.py into a package — V1

Status: approved 2026-11-26 with the recommended answers (package `md_view`, tests patch the defining module,
three PRs, no "copy one file"). The plan in `tasks/plan.md` adds one module, `links.py`, and corrects four cut
points that the graph showed; where they differ, the plan wins.

## Objective

`md-view.py` is 4,400 lines in one file. Every PR touches it, and the code graph shows it as the least
cohesive part of the repo (0.054). Move the code into a small package so a change touches one module, and keep
`md-view.py` as the launcher.

This is a **pure move**: no behaviour changes, no fixes, no renames. The person who runs md-view sees no
difference.

It replaces the "One file" non-negotiable in AGENTS.md. The person chose this option (option 3) on 2026-11-26.

## Assumptions (correct me before I plan)

1. Package name `md_view` (a hyphen cannot be imported, and `mdview` is already the module name the tests give
   to `md-view.py`).
2. `md-view.py` stays at the repo root and stays the thing users run and the registry command points at.
3. Moving `BASE_CSS` and `VIEWER_JS` out into `.css` and `.js` files is a **separate, later** change. Here they
   stay Python strings, in their own modules.
4. "Copy just one file" stops working: the launcher needs the `md_view/` folder next to it.
5. The sibling Rust port uses md-view.py as its specification. It will be told in the PR; its source is not
   touched.
6. Oldest supported Python stays 3.9. Every module keeps `from __future__ import annotations`.
7. **Start only after PR #21 is merged.** The work branches from an updated `main`
   (`git pull --ff-only origin main`, then a new branch, or a rebase of this one). PR #21 edits `read_text`
   and `_parse_document`, which move; the "old L..." line numbers below come from `main` before #21 and shift
   by about 30 lines. The cut points are re-read from the merged `main` in the Plan phase.

## Tech stack

Python 3.9+, pywebview, markdown, pygments (requirements.txt, unchanged). No new dependency.

## Commands

```
Tests:          .venv/Scripts/python.exe -m pytest tests -q
Old-Python:     "C:/Program Files/Python311/python.exe" -m compileall -q md-view.py md_view
Run:            python md-view.py samples/demo.md
Run (installed): python -m pip install . && md-view.py --help
Local review:   coderabbit review --agent --uncommitted
Graph:          graphify update .      (the post-commit hook also does it)
```

## Project structure (target)

Layer order, bottom first. A module imports only from layers below it, never above.

```
md-view.py              launcher: sets sys.path, calls md_view.cli.main()   (~20 lines)
md_view/
  __init__.py           __version__, APP_NAME; imports nothing heavy
  config.py             file types, constants, data_dir, prefs, theme        (old L39-158)
  mermaid_assets.py     find/fetch/verify mermaid.js                          (old L159-228)
  markdown_render.py    Markdown to HTML, mermaid fence preprocessor          (old L229-370)
  styles.py             BASE_CSS                                              (old L371-985)
  viewer_js.py          VIEWER_JS                                             (old L986-2202)
  documents.py          classify, read_text, per-document rendering, delimited text  (old L2441-2618)
  trees.py              sidebar trees                                         (old L2619-3066)
  page.py               HTML assembly: build_page, toolbar, tabs              (old L2203-2440)
  app.py                Viewer, Api                                           (old L3067-3880)
  single_instance.py    InstanceServer, instance_lock, hand_off, _path_from_href  (old L3881-4047)
  windows_assoc.py      register / unregister file associations               (old L4048-4190)
  cli.py                build_parser, main                                    (old L4191-end)
tests/                  unchanged layout; patch targets move (see Testing)
```

The exact cut points, and the import order, are settled with the graph in the Plan phase.

## Code style

Unchanged. One example of how a module refers to another, so that a patch on the defining module works:

```python
# md_view/page.py
from . import mermaid_assets          # module, not "from .mermaid_assets import find_mermaid"

path = mermaid_assets.find_mermaid()  # a test patching mermaid_assets.find_mermaid takes effect
```

## Testing strategy

- **The hazard:** about 14 tests patch names on the loaded module (`find_mermaid`, `data_dir`, `_os_open`,
  `_IS_MAC`, `Viewer`, `InstanceServer`, `hand_off`, `PREFS_PATH`, `load_prefs`, `save_prefs`, ...). A function
  that did `from .x import name` keeps the old object, so a patch on any other module does nothing and the test
  then touches the real disk or network. Rule: modules call each other through the module (`x.name()`), and the
  tests patch the module that defines the name.
- **Proof that no logic changed:** a throwaway script compares, with `ast`, every top-level function, class and
  constant of the old file against the new modules. Each must appear exactly once, with an identical body once
  `module.name` is read as `name` where `module` is one of the new `md_view` modules and defines `name` (never
  `os.`, `json.` or any other prefix), and the function has no local or parameter of that name. The only other
  allowed edits are the two `__file__` lookups that must keep following the running `md-view.py` launcher (the repo copy, or the one `pip install .` put in
  `Scripts/`): `assets/` in
  `vendored_mermaid()` and the script path in `_launch_command()` (see below); the script reports them as
  changed, and they are checked by eye. The script is not committed.
- **Proof that no patch is silently dead:** each patched name in the tests must be one that the code under test
  really looks up through that module. A test that still passes after its patch is removed is a smell; the
  Plan lists those.
- **Start-up weight:** a test records `sys.modules` after the hand-off path (`hand_off` only) and fails if it
  imports any module outside `md_view` that it does not import today (no third-party module, and none of
  `urllib`, `secrets`, `tempfile`, `webbrowser`, `csv`, `hashlib`, `ctypes`, `winreg`; `shutil` is already
  imported by `argparse` on Python 3.12).
- **Real-window check** (AGENTS.md): needs a desktop. Open a Markdown file with a diagram, a CSV, an SVG and an
  image; follow a link; use find; open a second file from another launch (hand-off); close.
- The existing 62 tests keep their meaning. Only their patch targets change.

## Boundaries

- **Always:** move code without editing it; one module per commit; run the tests after every commit; keep
  `from __future__ import annotations`; keep the lazy imports (heavy modules imported where used).
- **Ask first:** any change to packaging (`setup.py`, `MANIFEST.in`, run.ps1 / run.bat); any edit to a test
  beyond its patch targets, except tightening an assertion so that removing the test's patch makes it fail (the
  liveness proof under Testing strategy requires that); a cycle between modules that forces moving a function to another layer.
- **Never:** change behaviour or logic in a move commit; rename a public name; fix an audit finding or a bug in
  the same PR; add a dependency; touch the sibling Rust port.

## Things that break if done carelessly (checked in the code)

1. `vendored_mermaid()` finds `assets/` with `Path(__file__).parent`; moved into the package, that would look
   in `md_view/assets`. It must still look beside the running `md-view.py` launcher, as today.
2. `_launch_command()` writes `Path(__file__)` into the Windows registry; it must keep pointing at `md-view.py`,
   not at a module inside the package.
3. `setup.py` reads the version from a line in `md-view.py` and installs `md-view.py` as a script; both change.
4. `tests/conftest.py` loads `md-view.py` by path under the module name `mdview`; it must put the repo root on
   `sys.path` so that `md_view` imports.
5. The single-instance hand-off launch "imports almost nothing" (AGENTS.md). The package `__init__` and the
   launcher must not import the app on that path.
6. A circular import between `app`, `page` and `documents` is easy to create. The layer order above forbids it.

## Success criteria

- [ ] `python -m pytest` passes with the same number of tests (62 plus the start-up test), none deleted.
- [ ] The `ast` comparison finds every old top-level name exactly once in the new modules, bodies identical.
- [ ] `python md-view.py <file>` works from a different working directory; `--help`, `--version`,
      `--fetch-assets` and `--register` work.
- [ ] `pip install .` installs the package and the script; `md-view.py file.md` runs from Scripts.
- [ ] The registry command written by `--register` still names `md-view.py`.
- [ ] The hand-off launch imports no module outside `md_view` that it did not import before.
- [ ] All modules compile on Python 3.11 (3.9 is not installed here; stated in the PR).
- [ ] Real-window check done by the person, or reported as not done.
- [ ] AGENTS.md ("One file" rule and the map of the code), README and the graph are updated.
- [ ] Each PR is reviewed with `agent-skills:code-reviewer`; the bridge and hand-off modules also with
      `agent-skills:security-auditor`.

## Out of scope (deferred)

- Moving `BASE_CSS` / `VIEWER_JS` into `.css` / `.js` files (option 2): possible later, now cheap once they have
  their own modules.
- Splitting the `Viewer` class itself (it is about 800 lines).
- The open audit findings (network images, registry default handler, JS tests, hand-off server).
- Type hints, lint rules, renames.

## Open questions (need your answer)

1. Package name `md_view`: OK?
2. Is it acceptable that "copy one file" no longer works, and that `pip install .` now ships a package?
3. Test patches: patch the **defining** module (recommended), or keep `md-view.py` re-exporting every name so
   the tests keep saying `mdv.name`? The second makes patches silently dead (see Testing), so I advise against.
4. One PR for the whole move, or three in order: (1) leaves: config, mermaid_assets, markdown_render, styles,
   viewer_js; (2) documents, trees, page; (3) app, single_instance, windows_assoc, cli, launcher, docs? I advise
   three: each passes the tests alone, and a 4,400-line diff is too much to review at once.
5. Will you run the real-window check at the end of each PR?
