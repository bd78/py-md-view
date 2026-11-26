# Implementation Plan: split md-view.py into the md_view package

Source spec: [spec/SPEC-package-split.md](../spec/SPEC-package-split.md) (approved 2026-11-26 with the
recommended answers: package `md_view`, tests patch the defining module, three PRs).
Tasks: [tasks/todo.md](todo.md).

## Overview

Move the 4,400 lines of `md-view.py` into 13 modules under `md_view/`, in three PRs, without changing any
behaviour. `md-view.py` becomes a launcher of about 20 lines. Every slice leaves the app working and the tests
green, so each PR can stand alone.

## What the graph and the code showed (this changes the spec's cut points)

The `# ----` banners in `md-view.py` are not the real boundaries. Checked against the graph (366 nodes) and the
definitions:

1. **No import cycle.** The graph's only two-way pair is `app` and `single_instance`. `InstanceServer` calls
   `viewer.open_tab()` and `viewer._raise()` on an object it is handed, so it needs no import of `app`.
2. **`_path_from_href`, `_is_network_path`, `_resolve_local`, `_os_open`** sit in the single-instance section
   (L4015-4055) but `Viewer.open_path` uses them. They are link and OS helpers: a new low-layer module
   `links.py`. This adds one module to the spec's list.
3. **L2927-3066 is not tree code.** The "Sidebar trees" banner covers it, but `invalidate_document`,
   `document_parts`, `_parse_document` belong to `documents.py`, and `render_document`, `render_welcome` and
   `render_error` belong to `page.py`. The tree code proper is L2622-2925.
4. **`_IS_MAC`, `_IS_WINDOWS`, `_WIN_HIDDEN_ATTRS`** (L2626-2628) are platform constants used by `Viewer` and
   the trees; they go to `config.py`. `_drop_stale_bridge_replies` (L3070) goes with `app.py`.
5. **`_warm_renderers`, `fetch_then_repaint`** live in the CLI section and go to `cli.py`; `wants_mermaid` is
   nested inside `main` and moves with it.

## Layers (a module imports only from lower layers)

```
L0  config            file types, constants, platform flags, data_dir, prefs, theme
L1  links             _path_from_href, _is_network_path, _resolve_local, _os_open
    mermaid_assets    find / fetch / verify mermaid.js
    markdown_render   render_markdown, mermaid fence preprocessor, _task_lists
    styles            BASE_CSS, pygments_css
    viewer_js         VIEWER_JS
L2  documents         classify, read_text, delimited text, svg_dimensions, document cache, _parse_document
    trees             dir_entries, filesystem_roots, build_fs_tree, build_doc_tree and helpers
    single_instance   InstanceServer, instance_file, instance_lock, hand_off   (duck-types the viewer)
L3  page              build_page, toolbar, tabs, sidebar HTML, render_document / welcome / error
L4  app               Viewer, Api, _drop_stale_bridge_replies
L5  windows_assoc     register / unregister
    cli               build_parser, main, wants_mermaid, _warm_renderers
```

## Test patch map (the hazard in the spec)

Callers refer to other modules as `module.name()`, so a patch on the defining module takes effect:

| Test patches | New target |
|---|---|
| `find_mermaid`, `vendored_mermaid`, `fetch_mermaid` | `md_view.mermaid_assets` |
| `data_dir`, `PREFS_PATH`, `load_prefs`, `save_prefs`, `_IS_MAC` | `md_view.config` |
| `_os_open` | `md_view.links` |
| `_windows_drives` | `md_view.trees` |
| `hand_off`, `InstanceServer`, `instance_lock` | `md_view.single_instance` |
| `Viewer`, `_drop_stale_bridge_replies` | `md_view.app` |

Each task moves the code, rewrites its callers to `module.name`, and retargets the patches **in the same
commit**, so no commit has a dead patch. The task list's last step for each module re-runs the tests with the
patch removed, to prove it was live.

## Slices

House rule 18 (2026-11-26) asks for one small change per pull request, so each task is its own PR, merged
before the next starts. "PR A", "PR B" and "PR C" below (and in the task list) name groups of those task
PRs, in order, with a checkpoint after each group.

- **PR A, leaves:** scaffold and baselines, then `config`, `links`, `mermaid_assets`, `markdown_render`,
  `styles`, `viewer_js`.
- **PR B, middle:** `documents`, `trees`, `page`.
- **PR C, top:** `single_instance`, `app`, `windows_assoc`, `cli`, the launcher, `setup.py`, and the docs
  (AGENTS.md, README, the code map).

Each PR starts from an updated `main`, after the previous one is merged. The start of PR A also waits for the
open PR #21 and its partial-BOM follow-up.

## Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| A patch on the wrong module is silently dead | High: a test touches the real disk or network | patch map above; per-module "remove the patch, the test must fail" check |
| `__file__` moves with the code (`assets/`, the registry command) | High: no diagrams offline; registry points at a module | tasks T4 and T14 name them; a test asserts `vendored_mermaid()` still finds `<repo>/assets` |
| Hand-off launch gets heavier | Medium: slower start of every second launch | T1 records the `sys.modules` baseline first; a test fails on any new import |
| An import cycle appears when a function lands in the wrong layer | Medium | layer table; `python -c "import md_view.<m>"` for each module in isolation |
| `pip install .` forgets the package | High: installed script cannot start | T2 adds `packages=["md_view"]` with the first module; every PR from then on installs into a scratch venv and runs `--help` |
| 4,400-line diff is unreviewable | Medium | three PRs; one module per commit; the `ast` comparison, not eyes, proves a pure move |
| Python 3.9 syntax slips in | Medium | `from __future__ import annotations` in every module; compile on 3.11 and parse every module with `ast.parse(src, feature_version=(3, 9))`, which rejects newer syntax such as `match` (3.9 itself is not installed here, stated) |

## Agents and skills (named per step)

- **Mapping:** `graphify` CLI and the report (done above).
- **Each task:** `incremental-implementation` and `test-driven-development` skills; the plain tools.
- **Each commit:** the `git-commit` skill, with the local `coderabbit` CLI review.
- **Each PR:** the `pr` skill, with the `pr-manager` agent (open, then check rounds).
- **Before each PR:** `agent-skills:code-reviewer` agent on the diff; for PR B and C also
  `agent-skills:security-auditor` on `page`, `app` and `single_instance` (CSP, bridge, hand-off).
- **Docs task:** `documentation-and-adrs` skill.

## Open questions

- Is the extra module `links.py` (finding 2) acceptable? It is a plan-level addition to the spec.
- Will you run the real-window check at the end of each PR? (spec question 5, still open)
