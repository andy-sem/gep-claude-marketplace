# Python Port P6 (destructive-guard `gate_scripts`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> P6 is **one package** (one commit). Tasks 1–4 do not commit; Task 5 commits.
> Written ahead of P2–P5 landing: before starting, re-check names and counts against the committed tests and adjust this file.

**Goal:** `destructive_guard.gate_scripts`: which project files a Bash command runs (`bash x.sh`, `node x.mjs`, `python x.py`, `pnpm run`, `npm test`, workflows, `terraform test`, `docker run -w`, `cd`/`pushd`, variables), following `source` and imports breadth-first within limits, and the scan that asks when a script calls a gated program or a forbidden pattern. The P2 `gate-scripts` bridge tests are retargeted.

**Architecture:** port `gate-scripts.mjs` section by section (project root and paths → command targets → following sources/imports → scan). It uses the P5 tokenizer (`split_command`, `strip_wrappers`, `nested_shell_string`) and P4 `rules`. File access stays read-only, bounded (`MAX_FILE_BYTES`, `MAX_FOLLOW_DEPTH`, `MAX_FILES`), symlink-aware (real path must stay inside the project root).

**Tech Stack:** Python ≥ 3.14 stdlib (`os`, `pathlib`, `re`, `json`), pytest.

**Spec:** `lib/gate-scripts.mjs`; tests `tests/test_gate_scripts.py` (P2) and the script rows of `tests/test_gate_hook.py`, `tests/test_check.py` (`--cwd resolves scripts`); README §Scripts.

**Paths** are relative to `plugins/destructive-guard/` unless they start with `docs/` or `testkit/`.

## Global Constraints

- Conventions of `docs/plans/python-port-p4.md` §Conventions.
- No change to `lib/*.mjs`, `hooks/*`, `packs/`, `jev/`, JS tests; node suites green (735 / 68).
- Exit criterion: `tests/test_gate_scripts.py` has no bridge; `uv run pytest` green.
- `glob_to_regexp` returns a Python `re.Pattern` with the same matches as the JS `RegExp` (`**/`, `**`, `*`, `?`, rest literal, anchored).
- Public repo hygiene as in `CLAUDE.md`.

## Review Focus

- Path escape: a symlink or `..` that leaves the project root → a problem entry ("outside project"), never a read; `realpath` failures → unreadable problem, never an exception out of `collect_scripts`.
- Limits: exactly the JS constants; reading only the first `MAX_FILE_BYTES` (binary-safe decode `utf-8`, `errors="replace"`, as JS does with `toString("utf8")`).
- Order: breadth-first, files in collection order (Jev payload order depends on it, P7).
- Unparsable command → empty collection (rule layer decides), not an exception.

---

### Task 1: Project root, paths, globs

**Files:** Create `lib/destructive_guard/gate_scripts.py`. Modify `tests/test_gate_scripts.py` (retarget `findProjectRoot`, `globToRegExp`, exempt-path rows).

**Interfaces (Produces):** `MAX_FILE_BYTES = 65536`, `MAX_FOLLOW_DEPTH = 3`, `MAX_FILES = 32`, `find_project_root(cwd, env) -> str`, `glob_to_regexp(glob) -> re.Pattern`; internal `real_or_self`, `inside`, `rel_path`, `is_exempt_path`.

- [ ] **Step 1:** Retarget the rows (remove `js_regexp`), run → fail → port → pass.

### Task 2: Command targets

**Files:** Modify `lib/destructive_guard/gate_scripts.py`, `tests/test_gate_scripts.py`.

**Interfaces (Produces):** `run_targets(raw_tokens, rules, *, cwd, root, depth=0) -> list[dict]` (`{"path", "cwd"}` / workflow / package-script entries as JS); internal `unresolvable`, `leading_options`, `node_operands`, `python_operand`, `first_operand`, `read_scripts`, `workflow_name`, `resolve_workflow`, `option_value`, `terraform_test_targets`, `expand_vars`, `command_targets`.

- [ ] **Step 1:** Retarget the target rows (`collect_many` → list comprehension over `collect_scripts`, implemented in Task 3; until then mark the run red). Port targets first, then Task 3.

### Task 3: Following and collection

**Files:** Modify `lib/destructive_guard/gate_scripts.py`.

**Interfaces (Produces):** `collect_scripts(command, rules, *, cwd, root) -> dict` (`{"files": [{path, rel, kind, content, …}], "problems": [...]}` as JS); internal `source_targets`, `resolve_import`, `import_targets`, `kind_of`, `read_head`, `is_file`.

- [ ] **Step 1:** Run the retargeted collection rows → pass. Symlink/outside-project rows included.

### Task 4: Scan

**Files:** Modify `lib/destructive_guard/gate_scripts.py`.

**Interfaces (Produces):** `scan_scripts(collected: dict | None, rules) -> dict | None` (an `ask` result or `None`); internal `ask`, `escape_re`, `program_names`.

- [ ] **Step 1:** Retarget the scan rows; add `test_scan_matches_js_on_corpus_projects`: for each script-related row of P1 `test_gate_hook.py`, the same project and command through Python `scan_scripts(collect_scripts(...))` gives the reason the hook test expects. Run → pass.

### Task 5: Verify, commit

- [ ] **Step 1:** Node suites (735 / 68), `uv run pytest`, `uv run ruff check .`; report `GD_IMPL=py` failure count.
- [ ] **Step 2:** `docs/plans/python-port.md` §4: mark P6 done (link this file).
- [ ] **Step 3:** One commit by file name, `Python port P6: destructive_guard gate_scripts`, trailer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Do not push.
