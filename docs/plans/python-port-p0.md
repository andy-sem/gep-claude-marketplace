# Python Port P0 (groundwork) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> Per the general plan, P0 is **one package**: one implementer, one reviewer, **one commit** at the end (Task 6). Tasks below do not commit.

**Goal:** a Python dev/test toolchain next to the JS one (uv, pytest, ruff, CI), the shared test helpers later packages build on (`impl` fixture, JS bridge, interpreter lookup), the `PORTING.md` parity maps, and the D1b version-check entry stubs. No runtime behaviour changes: hooks still run JS.

**Architecture:** repo-level helpers live in a `testkit/` package (importable from every test via pytest `pythonpath`), repo-level tests in `tests/`, plugin tests in `plugins/<name>/tests/`. Entry stubs are 3.7-parsable files that check the version and then import a per-plugin package that holds only placeholders in P0.

**Tech Stack:** Python ≥ 3.14 stdlib, uv, pytest, ruff, node (for the bridge, until P14), GitHub Actions.

**Spec:** `docs/plans/python-port.md` (D1–D4a, §3, P0 in §4).

## Global Constraints

- Runtime code: Python ≥ 3.14, stdlib only. Dev only: `pytest`, `ruff` (uv dependency group `dev`).
- `requires-python = ">=3.14"`, ruff `target-version = "py314"`, `.python-version` = `3.14`.
- Entry stubs parse with `ast.parse(src, feature_version=(3, 7))`.
- Too-old message, exact: `needs Python >= 3.14 (found X.Y at <sys.executable>); set GATE_INFRA_PYTHON` + newline on stderr, exit code `3`.
- D1a lookup order: `GATE_INFRA_PYTHON` if set and non-empty, else first of `python3.14`, `python3` on `PATH`; always run with `-I`.
- `GD_IMPL=js|py`; default `js` for both plugins until their cutover.
- Public repo hygiene (`CLAUDE.md`): fictional tools only, no named MCP servers, no source-project names.
- `node --test` suites stay green and untouched.

## Review Focus

- A stub run with `-I` must still find its package: `-I` implies `-P` (script dir **not** on `sys.path`), so each stub inserts its package dir itself → covered by the "3.14 imports the package" test running the stub with `-I` from an unrelated cwd.
- A stub run by an old interpreter must print the message, not a `SyntaxError` → test with a real old interpreter (`OLD_PYTHON` / `python3.9`…`python3.13` / `/usr/bin/python3` below 3.14), skipped only if none exists; CI installs 3.9.
- A planted `json.py`/`destructive_guard.py` in the cwd must not be imported → stub test runs with cwd = a tmp dir containing a `destructive_guard.py` that exits 99.
- Bridge must surface JS exceptions as Python exceptions with the JS error name, not as JSON parse errors → error-case test.
- `GD_IMPL` typo must fail loudly, never silently fall back to `js` → test.
- (Moved out of P0) the D1a lookup tests that go through `gate.sh` (fake 3.9 `python3` → ask, missing `GATE_INFRA_PYTHON` → ask, no Python → ask, `python3.14` preferred) need `gate.sh` to start Python, which is P9; the same cases for `run-python.sh` land in P10. P0 tests the lookup logic in `testkit.pythons.find_python` only.

---

### Task 1: Dev toolchain, CI and docs

**Files:**
- Create: `pyproject.toml`, `.python-version`, `.gitignore`, `uv.lock` (generated), `conftest.py` (root, empty except a docstring for now), `tests/test_toolchain.py`
- Modify: `.github/workflows/test.yml`, `CLAUDE.md` (section "Test and validate")

**Interfaces:**
- Produces: `uv sync` + `uv run pytest` + `uv run ruff check .` work from the repo root; `testkit` is importable from any test.

- [ ] **Step 1:** `pyproject.toml`: `[project] name = "gep-claude-marketplace"`, `version = "0.0.0"`, `requires-python = ">=3.14"`, `dependencies = []`; `[dependency-groups] dev = ["pytest>=8", "ruff>=0.8"]`; `[tool.uv] package = false`; `[tool.pytest.ini_options] testpaths = ["tests", "plugins"]`, `addopts = ["--import-mode=importlib"]`, `pythonpath = ["."]`; `[tool.ruff] target-version = "py314"`. `.python-version`: `3.14`. `.gitignore`: `.venv/`, `__pycache__/`, `.pytest_cache/`, `.ruff_cache/`.
- [ ] **Step 2: Write the test** `tests/test_toolchain.py`:

```python
import sys, tomllib, pathlib
ROOT = pathlib.Path(__file__).resolve().parents[1]

def test_running_on_floor_or_newer():
    assert sys.version_info >= (3, 14)

def test_pyproject_pins_floor():
    cfg = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert cfg["project"]["requires-python"] == ">=3.14"
    assert cfg["project"]["dependencies"] == []
    assert cfg["tool"]["ruff"]["target-version"] == "py314"
    assert (ROOT / ".python-version").read_text().strip() == "3.14"
```

- [ ] **Step 3:** Run `uv sync && uv run pytest tests/test_toolchain.py -v` → 2 passed. Run `uv run ruff check .` → clean.
- [ ] **Step 4:** CI: add a job `python` to `.github/workflows/test.yml` next to the existing node job (which stays unchanged). Matrix `python: ["3.14", "latest"]`. Steps: checkout; `actions/setup-node@v4` (node 22, the bridge needs it); `astral-sh/setup-uv@v6`; `uv python install 3.9` and `echo "OLD_PYTHON=$(uv python find 3.9)" >> "$GITHUB_ENV"`; `uv sync --python <3.14 | >=3.14 for latest>` (use `UV_PYTHON` from the matrix: `3.14` or `>=3.14`); print `uv run python -V`; `uv run ruff check .`; `uv run pytest`.
- [ ] **Step 5:** `CLAUDE.md` "Test and validate": add `uv sync` (once) and `uv run pytest` (with `GD_IMPL=py` to run against the Python port), say dev tools need uv and Python 3.14; keep the node commands (they go in P14).

### Task 2: Interpreter lookup and the `impl` fixture

**Files:**
- Create: `testkit/__init__.py` (exports `REPO`, `PLUGINS`), `testkit/pythons.py`, `testkit/impl.py`, `tests/test_testkit_impl.py`
- Modify: `conftest.py` (root): fixtures `impl` and `old_python`

**Interfaces:**
- Produces:
  - `testkit.REPO: Path`, `testkit.PLUGINS: Path` (`REPO / "plugins"`), `DG = PLUGINS / "destructive-guard"`, `GD = PLUGINS / "gated-dev-simple-workflow"`.
  - `testkit.pythons.find_python(env: Mapping[str, str]) -> str | None` — D1a: non-empty `env["GATE_INFRA_PYTHON"]` returned as is (even if missing; the shim must then fail), else `shutil.which("python3.14", path=env.get("PATH"))`, else `shutil.which("python3", ...)`, else `None`.
  - `testkit.pythons.find_old_python() -> str | None` — `OLD_PYTHON` env if set, else first of `python3.13`…`python3.9`, `/usr/bin/python3` whose `-c "import sys;print(sys.version_info[:2]<(3,14))"` prints `True`.
  - `testkit.impl.Impl` (frozen dataclass): `name: Literal["js", "py"]`, `plugin: str`; methods returning `list[str]` argv: `gate_hook()` → `["bash", DG/hooks/gate.sh]`, `env_guard()` → `["bash", DG/hooks/env-guard.sh]`, `check()` → js `["node", DG/lib/check.mjs]` / py `[python, "-I", DG/lib/check.py]`, `launch()` → `.../scripts/launch.mjs` / `scripts/launch.py`, `watch_pr()` → `scripts/watch-pr.mjs` / `scripts/watch_pr.py`, `notify()` → js `["bash", GD/hooks/notify.sh]` / py `["bash", GD/hooks/run-python.sh, GD/hooks/notify.py]`; `env() -> dict[str, str]` → js `{"GATE_INFRA_NODE": shutil.which("node")}` / py `{"GATE_INFRA_PYTHON": python}`. `python` comes from `find_python(os.environ)`; `py` with no Python found raises `RuntimeError`.
  - `testkit.impl.DEFAULT_IMPL: dict[str, str] = {"destructive-guard": "js", "gated-dev-simple-workflow": "js"}`.
  - `testkit.impl.select_impl(plugin: str, env: Mapping[str, str]) -> Impl` — `GD_IMPL` (if non-empty) wins for every plugin; value not `js`/`py` → `ValueError("GD_IMPL must be js or py, got ...")`; unknown plugin → `ValueError`.
  - Fixture `impl`: plugin inferred from `request.path` (the dir under `plugins/`); a test outside `plugins/` using it → `pytest.UsageError`.
  - Fixture `old_python`: `find_old_python()` or `pytest.skip("no Python < 3.14 available")`.

- [ ] **Step 1: Write the tests** `tests/test_testkit_impl.py`:
  - `test_default_is_js_for_both_plugins`: `select_impl(p, {}).name == "js"` for both plugins.
  - `test_gd_impl_overrides`: `select_impl("destructive-guard", {"GD_IMPL": "py"}).name == "py"`.
  - `test_gd_impl_typo_raises`: `pytest.raises(ValueError, match="GD_IMPL")` for `"pyhton"`.
  - `test_js_entry_points_exist`: for the js impl of each plugin, the last path element of every argv it owns (`gate_hook`, `env_guard`, `check` for DG; `launch`, `watch_pr`, `notify` for GD) is an existing file.
  - `test_find_python_prefers_env` (`{"GATE_INFRA_PYTHON": "/nope", "PATH": ...}` → `"/nope"`), `test_find_python_prefers_314_over_python3` (tmp dir with executable fakes `python3` and `python3.14`, `PATH` = that dir → ends with `python3.14`), `test_find_python_falls_back_to_python3`, `test_find_python_none` (empty tmp dir as `PATH` → `None`), `test_empty_env_var_is_ignored` (`GATE_INFRA_PYTHON=""`).
- [ ] **Step 2:** `uv run pytest tests/test_testkit_impl.py -v` → fails on import (`testkit` missing).
- [ ] **Step 3:** Implement `testkit/__init__.py`, `testkit/pythons.py`, `testkit/impl.py` and the two fixtures in `conftest.py` as specified above.
- [ ] **Step 4:** Same command → all pass.

### Task 3: JS bridge

**Files:**
- Create: `testkit/_bridge.mjs`, `testkit/bridge.py`, `tests/test_testkit_bridge.py`

**Interfaces:**
- Produces:
  - `node testkit/_bridge.mjs <module> <export>` with a JSON array of arguments on **stdin** (not argv: argument size). `<module>` is a file name without extension under `plugins/destructive-guard/lib/` (`paths`, `config`, `gate-engine`, …). If the export is a function it is called with the args and awaited; otherwise its value is returned (args must be `[]`). Result on stdout as JSON with a replacer: `undefined` → `null`, `Set` → array, `Map` → object, `RegExp` → `{"$regexp": source, "flags": flags}`. Thrown error → exit 1, stdout `{"$error": {"name": e.name, "message": e.message}}`.
  - `testkit.bridge.bridge(module: str, export: str, *args: Any) -> Any`; `testkit.bridge.BridgeError(Exception)` with `.name: str` and `.message: str`, raised for a `$error` result; any other non-zero exit / non-JSON stdout raises `RuntimeError` with stderr.

- [ ] **Step 1: Write the tests** `tests/test_testkit_bridge.py`:

```python
def test_calls_function(tmp_path):
    assert bridge("paths", "projectDir", {"CLAUDE_PROJECT_DIR": str(tmp_path)}, "/") == str(tmp_path.resolve())

def test_reads_constant():
    assert bridge("config", "DEFAULT_CHECKS") == ["destructive"]

def test_regexp_is_encoded():
    assert bridge("gate-scripts", "globToRegExp", "*.sh") == {"$regexp": "^[^/]*\\.sh$", "flags": ""}

def test_js_error_becomes_bridge_error():
    with pytest.raises(BridgeError) as e:
        bridge("config", "readConfig", {"GATE_CHECKS": "nope"})
    assert e.value.name == "ConfigError"
    assert 'unknown pack "nope"' in e.value.message

def test_unknown_export_fails():
    with pytest.raises(BridgeError):
        bridge("paths", "noSuchExport")
```

  Also `test_async_function_is_awaited`: `bridge("check", "effectiveConfig", {"CLAUDE_PROJECT_DIR": str(tmp_path)})` returns a `dict` (not `{}` from an unawaited promise). Check the actual `DEFAULT_CHECKS` and regex source against the JS before fixing the expected values.
- [ ] **Step 2:** `uv run pytest tests/test_testkit_bridge.py -v` → fails (no module).
- [ ] **Step 3:** Implement `_bridge.mjs` and `bridge.py`.
- [ ] **Step 4:** Same command → all pass.

### Task 4: D1b entry stubs

**Files:**
- Create (stubs): `plugins/destructive-guard/lib/gate_main.py`, `plugins/destructive-guard/lib/check.py`, `plugins/gated-dev-simple-workflow/scripts/launch.py`, `plugins/gated-dev-simple-workflow/scripts/watch_pr.py`, `plugins/gated-dev-simple-workflow/hooks/notify.py`
- Create (placeholder packages): `plugins/destructive-guard/lib/destructive_guard/{__init__,gate_main,check}.py`, `plugins/gated-dev-simple-workflow/scripts/gated_dev/{__init__,launch,watch_pr,notify}.py`
- Test: `plugins/destructive-guard/tests/test_entry_stubs.py`, `plugins/gated-dev-simple-workflow/tests/test_entry_stubs.py` (shared logic in `testkit/stubs.py` to avoid two copies)

**Interfaces:**
- Consumes: `old_python` fixture, `find_python` (Task 2).
- Produces:
  - Each stub: syntax any Python ≥ 3.7 parses (no f-strings with `=`, no walrus, no `match`, no annotations beyond 3.7). Too old → the Global Constraints message, `exit(3)`. Else insert the package's parent dir (DG: the stub's own dir `lib/`; GD: `scripts/`, from `hooks/notify.py` that is `../scripts`) at `sys.path[0]`, `from <pkg>.<mod> import main`, `sys.exit(main())`.
  - Placeholder module: `def main() -> int:` writes `<module>: not implemented yet` + newline to stderr, returns `2`. P4+ replace these with the real code.
  - `testkit/stubs.py`: `STUBS: list[tuple[Path, str]]` = (stub path, package module) for all five, plus helpers used by both test files.

- [ ] **Step 1: Write the tests** (parametrised over the stubs of that plugin):
  - `test_stub_parses_as_python_37`: `ast.parse(src, feature_version=(3, 7))` does not raise.
  - `test_old_python_gets_exit_3(old_python)`: run `[old_python, "-I", stub]` → returncode `3`, stderr matches `^needs Python >= 3\.14 \(found 3\.\d+ at .+\); set GATE_INFRA_PYTHON\n$`, stdout empty.
  - `test_314_imports_package(tmp_path)`: `tmp_path` holds a planted `destructive_guard.py` and `gated_dev.py` (each `raise SystemExit(99)`); run `[find_python(os.environ), "-I", stub]` with `cwd=tmp_path` → returncode `2`, stderr `"<module>: not implemented yet\n"`.
- [ ] **Step 2:** `uv run pytest plugins -v -k entry_stubs` → fails (files missing).
- [ ] **Step 3:** Write the stubs and placeholders.
- [ ] **Step 4:** Same command → all pass (old-Python test runs locally if `/usr/bin/python3` or any `python3.9`–`3.13` exists; note in the report whether it ran or skipped).

### Task 5: `PORTING.md` parity maps

**Files:**
- Create: `plugins/destructive-guard/tests/PORTING.md`, `plugins/gated-dev-simple-workflow/tests/PORTING.md`, `testkit/porting.py`, `tests/test_porting.py`

**Interfaces:**
- Produces:
  - `PORTING.md` format: a short intro, then one table `| JS file | JS test | Python test |`. JS file is the basename (`gate-hook.test.mjs`), JS test the literal first argument of `test(` (template literals kept verbatim, e.g. `` destructive: ${label} -> ${expected} ``), `|` escaped as `\|`. Python test column: `todo`, `dropped: <reason>`, or `<path relative to the plugin>::<test_name>` (e.g. `tests/test_gate_hook.py::test_node_unavailable_asks`); several targets separated by `, `.
  - `testkit.porting.js_tests(plugin_dir: Path) -> list[tuple[str, str]]` — scans `test/*.test.mjs` with `(?<![.\w])test\(\s*(["'`])(.*?)(?<!\\)\1` (DOTALL off). Returns `[]` when `test/` is gone (after cutover).
  - `testkit.porting.read_map(path: Path) -> list[tuple[str, str, str]]`.
- [ ] **Step 1: Write the tests** `tests/test_porting.py`, parametrised over both plugins:
  - `test_every_js_test_is_mapped`: set of `js_tests` ⊆ set of `(file, name)` in the map; failure lists the missing ones.
  - `test_no_stale_rows`: while `test/` exists, every map row's `(file, name)` is in `js_tests`.
  - `test_targets_exist`: for every target that is not `todo` / `dropped: …`, the file exists and contains `def <test_name>(`.
  - `test_js_tests_found`: `js_tests` of destructive-guard has ≥ 200 entries and contains `("gate-hook.test.mjs", "node unavailable -> ask")` (guards the regex against silently matching nothing).
- [ ] **Step 2:** Run → fails.
- [ ] **Step 3:** Implement `porting.py`; generate both `PORTING.md` files once with a throwaway script (not committed) using `js_tests`, all rows `todo`.
- [ ] **Step 4:** `uv run pytest tests/test_porting.py -v` → pass.

### Task 6: Verify and commit

- [ ] **Step 1:** `node --test 'plugins/destructive-guard/test/*.test.mjs'` and `node --test 'plugins/gated-dev-simple-workflow/test/*.test.mjs'` → all pass, unchanged counts.
- [ ] **Step 2:** `uv run pytest` → all pass (list skips); `GD_IMPL=py uv run pytest tests` → pass; `uv run ruff check .` → clean; `claude plugin validate .` → ok.
- [ ] **Step 3:** In `docs/plans/python-port.md` §4 mark P0 done (link this file) and add the note that the `gate.sh` / `run-python.sh` lookup tests moved to P9 / P10.
- [ ] **Step 4:** Commit everything as one commit, message `Python port P0: toolchain, test kit, entry stubs` with a short body and the attribution trailer. Do not push.
