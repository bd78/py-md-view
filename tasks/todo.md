# Tasks: md_view package split

See [plan.md](plan.md). Verify command for every task:
`.venv/Scripts/python.exe -m pytest tests -q` and, from T1 on, the `ast` comparison script
(`<scratchpad>/ast_compare.py`, not committed).

## Task 0: Prerequisites (no code)
- [x] PR #21 (5 MB read cap) is merged on `origin/main`
- [x] The partial-BOM follow-up is merged (PR #22)
- [x] `main` pulled; one branch per task from now on (house rule 18)
- Acceptance: `grep -c MAX_TEXT_BYTES md-view.py` is not 0; `read_text` uses `data.decode` when not cut.

## PR A, leaves

### Task 1: Scaffold and baselines
- [x] Record the hand-off launch baseline and add `tests/test_startup_imports.py`: a fresh interpreter hands a
      file to a fake window and must not import `markdown`, `webview`, `pygments`, `urllib.request`, `secrets`,
      `tempfile`, `webbrowser` (`shutil` comes with `argparse`)
- [ ] Write the `ast_compare.py` script in the scratchpad and run it: old file vs itself passes
- `md_view/__init__.py` and the `conftest.py` path change move to Task 2, with the first module: alone they
  would only duplicate `__version__`.
- Acceptance: tests green, 1 new test, nothing moved yet. Files: `tests/test_startup_imports.py`, the spec and
  the plan.
- Size: S

### Task 2: config
- [ ] Move constants, file types, platform flags, `data_dir`, `assets_dir`, prefs, theme (old L39-158 and
      L2626-2628) to `md_view/config.py`; callers use `config.name`; retarget patches of `data_dir`, `PREFS_PATH`,
      `load_prefs`, `save_prefs`, `_IS_MAC`
- [ ] `md_view/__init__.py` (version, app name, no heavy import); `tests/conftest.py` puts the repo root on `sys.path`
- [ ] `setup.py`: `packages=["md_view"]` next to the script, so `pip install .` keeps working from the first move;
      the version is still read from `md-view.py` until Task 14
- [ ] Scratch venv: `pip install .`, then run the installed `md-view.py --help` from another directory
- Acceptance: `ast_compare` clean; each patch removed makes its test fail; `import md_view.config` alone works;
  the installed script starts.
- Size: M (config, md-view.py, setup.py, ~3 test files)

### Task 3: links
- [ ] Move `_path_from_href`, `_is_network_path`, `_resolve_local`, `_os_open` (old L4015-4055) to
      `md_view/links.py`; retarget the `_os_open` patches
- Acceptance: as T2; the network-share and app-bundle tests pass unchanged apart from the patch target.
- Size: S

### Task 4: mermaid_assets
- [ ] Move `vendored_mermaid`, `_mermaid_ok`, `cached_mermaid`, `find_mermaid`, `fetch_mermaid`; keep the
      `assets/` lookup pointing at `<repo>/assets` (use the repo root, not `Path(__file__).parent`); retarget
      `find_mermaid`, `vendored_mermaid`, `fetch_mermaid` patches
- [ ] Test: `vendored_mermaid()` finds `<repo>/assets/mermaid.min.js` when it exists
- Acceptance: as T2 plus the new test; the mermaid tests pass.
- Size: M

### Task 5: markdown_render
- [ ] Move `MERMAID_FENCE`, `CODE_FENCE`, `RAW_HTML_OPEN`, `_build_mermaid_extension`, `mermaid_block`,
      `_task_lists`, `RAW_META`, `_markdown_module`, `render_markdown`
- Acceptance: as T2; the 8 mermaid-fence tests and the `RAW_META` test pass.
- Size: S

### Task 6: styles
- [ ] Move `BASE_CSS` and `pygments_css` to `md_view/styles.py`
- Acceptance: as T2; the page tests that read the CSS pass.
- Size: XS

### Task 7: viewer_js
- [ ] Move `VIEWER_JS` to `md_view/viewer_js.py`
- Acceptance: as T2; `test_page_scripts.py` passes (it reads `VIEWER_JS`).
- Size: XS

### Checkpoint: PR A
- [ ] All tests pass; `ast_compare` clean; each module imports alone; compiles on Python 3.11; the scratch-venv
      `pip install .` check passes (every task PR repeats it once the package exists)
- [ ] `agent-skills:code-reviewer` agent on the diff, findings handled
- [ ] `pr` skill: `pr-manager` opens a draft; you mark ready; check rounds; you merge
- [ ] Real-window check by you (open a file with a diagram, a CSV, an image; follow a link)

## PR B, middle (starts from `main` after PR A is merged)

### Task 8: documents
- [ ] Move `classify`, delimited text, `read_text`, `human_size`, `svg_dimensions`, `invalidate_document`,
      `document_parts`, `_parse_document`, `_cut_note` (old L2441-2618 and L2927-3000)
- Acceptance: as T2; the read-text, CSV and cut-note tests pass.
- Size: M

### Task 9: trees
- [ ] Move the tree code (old L2622-2925: `dir_entries`, `documents_anchor`, `filesystem_roots`, `build_fs_tree`,
      `build_doc_tree` and helpers); retarget the `_windows_drives` patches
- Acceptance: as T2; the sidebar-root tests pass.
- Size: M

### Task 10: page
- [ ] Move `ICONS`, the HTML builders, `build_page`, `render_document`, `render_welcome`, `render_error`
- Acceptance: as T2; CSP, nonce and config-escape tests pass; no import of `app`.
- Size: M

### Checkpoint: PR B
- [ ] Tests, `ast_compare`, isolated imports, 3.11 compile
- [ ] `agent-skills:code-reviewer` and `agent-skills:security-auditor` agents (the page builder holds the CSP)
- [ ] `pr` skill and `pr-manager` agent as in PR A; real-window check by you

## PR C, top (starts from `main` after PR B is merged)

### Task 11: single_instance
- [ ] Move `InstanceServer`, `instance_file`, `instance_lock`, `hand_off`; retarget the patches
- Acceptance: as T2; the start-up import test still passes; no import of `app`.
- Size: M

### Task 12: app
- [ ] Move `Viewer`, `Api`, `_drop_stale_bridge_replies`; `Viewer` calls `links`, `trees`, `page`,
      `mermaid_assets`, `config` through the module; retarget the `Viewer` patches
- Acceptance: as T2; the bridge and hand-off tests pass; `Api` actions table unchanged.
- Size: M (largest move, about 800 lines)

### Task 13: windows_assoc
- [ ] Move the registry code; `_launch_command` keeps naming `md-view.py` (repo root, not the module)
- [ ] Test: the command string ends with `md-view.py`
- Size: S

### Task 14: cli, launcher, packaging
- [ ] Move `build_parser`, `main`, `wants_mermaid`, `_warm_renderers`, `fetch_then_repaint` to `md_view/cli.py`;
      `md-view.py` becomes the launcher
- [ ] `setup.py`: read the version from `md_view/__init__.py` (`packages` is already set since Task 2), keep the script;
      check `MANIFEST.in`, `run.ps1`, `run.bat`
- [ ] Scratch venv: `pip install .`, run `md-view.py --help` from another directory
- Acceptance: all success criteria in the spec's list for launch, install and registry.
- Size: M

### Task 15: docs
- [ ] AGENTS.md: replace the "One file" rule and the map of the code; README paths; spec status; `graphify`
      refresh; memory note
- Size: S

### Checkpoint: PR C (done)
- [ ] Everything in the spec's success criteria
- [ ] `agent-skills:code-reviewer` and `agent-skills:security-auditor` agents on `single_instance` and `app`
- [ ] `pr` skill and `pr-manager` agent; real-window check by you; `pip install .` check reported
