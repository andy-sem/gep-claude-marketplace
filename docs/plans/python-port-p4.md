# Python Port P4 (destructive-guard `paths`, rule loading, `config`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> P4 is **one package** (repo rule: one commit per work package). Tasks 1–4 do not commit; Task 5 makes the single commit.
> Re-checked against the committed P1–P3 code (2026-11-20); adjustments are listed under "Adjustments at execution" at the end.

**Goal:** the first Python modules of `destructive_guard`: `paths`, rule-pack loading (`rules`) and `config` (env → effective config, `build_rules`). The P2 `config` bridge tests and the rule-loading bridge tests are retargeted to them. Hooks keep calling JS (cutover is P9).

**Architecture:** bottom-up port next to the JS. Shared conventions for all of Phase 2 are set here (§Conventions) and reused by P5–P8. Rule loading (`loadRules`, `composeRules`, `loadPacks`, `parseRules`, `RulesError`, `PACKS_DIR`, `packPath`, `DEFAULT_PACKS`) lives in `gate-engine.mjs` today; it moves to its own module `rules.py` because `config` needs it and the parser (P5) does not. `gate_engine.py` re-exports it in P5 so the public surface matches the JS.

**Tech Stack:** Python ≥ 3.14 stdlib (`os`, `pathlib`, `json`, `re`), pytest.

**Spec:** `lib/paths.mjs`, `lib/config.mjs`, `lib/gate-engine.mjs` lines "Rules loading" (`regex` … `parseRules`); tests `plugins/destructive-guard/tests/test_config.py`, the `loadRules`/`composeRules` parts of `tests/test_gate_engine.py` and `tests/test_packs.py`; README §Configuration.

**Paths** in this file are relative to `plugins/destructive-guard/` unless they start with `docs/`, `testkit/` or `pyproject.toml`.

## Conventions (all of Phase 2)

- Package `plugins/destructive-guard/lib/destructive_guard/`; one module per JS module (`paths`, `rules`, `config`, `gate_engine`, `gate_scripts`, `gate_jev`, `check`, `gate_main`); functions in `snake_case` (`readConfig` → `read_config`), constants unchanged (`DEFAULT_CHECKS`).
- **Data keeps the JS shape:** dicts with the JS key spelling (`scriptPatterns`, `commandUnparsable`, `logPath`), JSON-compatible values, `None` for JS `null`/`undefined`, lists for JS `Set`s. Compiled regexes stay `re.Pattern` internally. This lets retargeted tests keep the JS expectations verbatim.
- **Errors keep the JS class names** (`ConfigError`, `RulesError`, `UnparsableError`, `JevConfigError`), subclasses of `Exception`, same messages. Retargeted tests replace `BridgeError.name == "X"` with `pytest.raises(X, match=...)`.
- **Retarget rule:** in a module marked `# retarget to destructive_guard in P<n>`, `bridge(m, f, *a)` → `f(*a)` from `destructive_guard.<m>`, `call(m, f, *a)` → `f(*a)`, `bridge_many([...])` → a list comprehension, `js_regexp(x)` → `x` (already a pattern). Remove the marker line when done; no bridge use left in the file.
- Regex: JS sources are compiled with `re` (D5). JS flag `i` → `re.IGNORECASE`; if a pack or user regex needs JS semantics Python lacks (`\d`/`\s` Unicode, `$` before a final newline), use `re.ASCII` / `\Z` in the compile helper, decided by the compile-all-packs test, never per pack.
- Type hints on public functions; `ruff` clean; no third-party imports at runtime.
- `pyproject.toml` `pythonpath` gains `plugins/destructive-guard/lib` so tests `import destructive_guard`.

## Global Constraints

- No change to `lib/*.mjs`, `hooks/*`, `packs/`, `jev/`, JS tests. Node suites green (735 / 68).
- Contract tests (`check --json`, `gate.sh`) still run JS by default; they must stay green with `GD_IMPL=js`.
- Exit criterion: `uv run pytest` green; the retargeted modules contain no `bridge`; `GD_IMPL=py` failures limited to CLI/hook tests (they need P8/P9).
- Public repo hygiene as in `CLAUDE.md`. Stage files by name; leave `lean-gate-model.md` and the `.gitignore` change alone.

## Review Focus

- Relative paths: `CLAUDE_PROJECT_DIR` (trimmed, empty = unset) → git root of `cwd` (a `.git` *file* counts, worktrees) → `cwd`; absolute paths kept untouched (no `resolve()` on them: symlinks must not change).
- Booleans: exactly `0/1/true/false/yes/no/on/off`, case-insensitive; anything else is a `ConfigError` with the JS message.
- `compose_rules`: string lists de-duplicated preserving first-seen order (JS `Set` order), duplicate rule id and "set by more than one pack" errors with the same text.
- Every pack regex compiles under `re` and matches what JS matched for the corpus (the corpus runs in P5; here, the compile test).

---

### Task 1: `paths`

**Files:** Create `lib/destructive_guard/paths.py`, `tests/test_paths.py`.

**Interfaces (Produces):** `project_dir(env: Mapping[str, str], cwd: str | Path) -> str`, `project_path(path: str, env, cwd) -> str`.

- [ ] **Step 1:** Tests: env dir wins (trimmed), git root via `.git` dir and `.git` file, falls back to `cwd`, absolute path kept as given, relative resolved. Expectations copied from `tests/test_config.py` relative-path rows.
- [ ] **Step 2:** Fail → implement → pass.

### Task 2: `rules` (rule loading and pack composition)

**Files:** Create `lib/destructive_guard/rules.py`, `tests/test_rules_loading.py`. Modify the rule-loading tests of `tests/test_gate_engine.py`, `tests/test_packs.py`, `tests/test_gate_scripts.py` (only their `loadRules`/`composeRules` calls).

**Interfaces (Produces):** `RulesError`, `PACKS_DIR: Path`, `DEFAULT_PACKS = ["base", "destructive"]`, `pack_path(name) -> str`, `load_rules(path) -> Rules`, `compose_rules(paths) -> dict`, `load_packs(paths) -> Rules`, `parse_rules(raw: dict) -> Rules`. `Rules` is a `dict` with the JS keys (`rules`, `runners`, `scriptPatterns`, `scriptExemptPaths`, `inertUnsafeFlags`, …), regex fields as `re.Pattern`.

- [ ] **Step 1: Tests first.** Retarget the P2 `loadRules` rows (runners, bad config, legacy/removed kinds, inert unsafe flags) and `composeRules`. Add `test_every_pack_regex_compiles` (each `packs/*.json` through `load_packs([...])`) and `test_parse_rules_matches_js_shape` (for each shipped pack: `json.loads` of the bridge `loadRules` result equals `to_json(load_rules(path))`, where `to_json` turns patterns into `{"$regexp", "flags"}` — the one place both impls are compared directly; drop it in P14 with the bridge).
- [ ] **Step 2:** Run → fail. Port `strArray` … `parseRules` one validator at a time; keep the error texts.
- [ ] **Step 3:** Run → pass; `ruff` clean.

### Task 3: `config`

**Files:** Create `lib/destructive_guard/config.py`. Modify `tests/test_config.py` (bridge rows only; hook/`check` rows stay contract tests).

**Interfaces (Produces):** `ConfigError`, `DEFAULT_CHECKS`, `available_packs(dir=PACKS_DIR) -> list[str]`, `read_config(env, *, cwd=None) -> dict` (keys as JS: `enabled`, `checks`, `rulesFile`, `rulesLegacy`, `disable`, `envGuard`, `strict`, `log`, …), `build_rules(config) -> Rules`; re-exports `RulesError`, `project_dir`, `project_path`.

- [ ] **Step 1:** Retarget the `readConfig`/`availablePacks`/`DEFAULT_CHECKS` rows (remove the marker). Add direct unit tests for `build_rules` that mirror the P2 contract rows (`GATE_CHECKS=none` + file, `GATE_DISABLE_RULES` unknown id, missing/broken file, duplicate id) so the Python path is covered before `check.py` exists (P8). Keep the contract rows unchanged.
- [ ] **Step 2:** Run → fail → implement → pass.

### Task 4: Corpus leg for `build_rules`

**Files:** Modify `plugins/destructive-guard/tests/test_corpus.py`.

- [ ] **Step 1:** Add `test_corpus_env_builds` parametrised over the three corpora: `build_rules(read_config(corpus_env))` does not raise and the rule ids it yields equal those of the JS (`bridge("config", "buildRules", call("config", "readConfig", env))` ids). This catches pack-composition drift before the engine exists.
- [ ] **Step 2:** Run → pass.

### Task 5: Verify, commit

- [ ] **Step 1:** Node suites (735 / 68), `uv run pytest`, `uv run ruff check .`, `claude plugin validate .`; report `GD_IMPL=py` failure count.
- [ ] **Step 2:** `docs/plans/python-port.md` §4: mark P4 done (link this file); note the `rules.py` split.
- [ ] **Step 3:** One commit by file name, `Python port P4: destructive_guard paths, rule loading, config`, trailer `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`. Do not push.

## Adjustments at execution

- Tests are in `tests/` (not `test/`); `test_config.py` row names are unchanged, so `PORTING.md` needed no edits. Node counts are not part of this package's changes (JS untouched).
- `test_gate_scripts.py` keeps its bridge: its `RULES = call("gate-engine", "loadRules", ...)` feeds parsed rules to the JS `gate-scripts`, which cannot take Python objects. Only `test_load_rules_validates_script_patterns_and_script_scan_exempt` was retargeted. `test_gate_engine.py` keeps the P5 marker (`splitCommand` is still bridged); `test_packs.py` has none left.
- The regex compile helper (`rules.compile_js_regex`) uses `re.ASCII` (JS `\d`, `\w`, `\b` are ASCII) and rewrites an unescaped `$` outside classes to `\Z` (JS `$` is end of input only) and `(?<name>` to `(?P<name>`. The parity test compares the JS bridge result after the same translation, with `\/` (which `RegExp.source` adds) unescaped.
- `pyproject.toml`: `pythonpath` and ruff `src` gain `plugins/destructive-guard/lib`.
- Trailer: Sonnet 5.5 (the model running the package), not Opus 5.5.
- Corpus leg: `test_corpus_env_builds` compares rule ids of `build_rules(read_config(env))` with the JS `buildRules` for the three corpora.
