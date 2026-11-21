# Lean Model of the Gate Decision Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> One work package (repo rule: one commit per package). Tasks 1–4 do not commit; Task 5 makes the single commit. Start after the Python port P1 commit has landed.

**Goal:** a Lean 4 model of how `destructive-guard` combines config, rule results, strictness and Jev into one hook decision, with machine-checked proofs of the theses below, plus an executable oracle that the Python test suite runs against the real hook (`GD_IMPL=js` now, `GD_IMPL=py` after the port), so the proofs stay tied to the code.

**Architecture:** a dependency-free Lake project in `formal/destructive-guard/` (dev-only, outside `plugins/` so it never ships to users). `GateModel/*.lean` holds the model and the theorems; `Oracle/Main.lean` builds `gate-oracle`, which reads abstract scenarios as JSON lines and prints the modelled decision. A Python test generates random abstract scenarios, turns each one into a real rules file + env + hook stdin + Jev mock answer, runs the hook through the P1 test kit and compares the result with the oracle.

**Tech Stack:** Lean 4 core only (no Mathlib, no Batteries; `Lean.Data.Json` for the oracle), Lake, elan; Python ≥ 3.14 + pytest + the P1 `testkit` (`run_hook`, `JevMock`, `temp_project`, `clean_env`).

**Spec:** the theses below (this document) + the behaviour in `plugins/destructive-guard/lib/gate-engine.mjs` (`classify` 1329–1400, `applyJev` 1422–1458, `gate` 1464–1497, `main` 1517–1563), `lib/gate-jev.mjs` (`readJevConfig` 87–140, `jevDecision` 529–549, `runJev` 563–616), `lib/config.mjs` (`readConfig`, `buildRules`), `hooks/gate.sh`. When the Python port replaces these files, the oracle test is the link; the line refs then point to `lib/destructive_guard/`.

## Theses

The model's output type deliberately includes the Claude Code decisions the gate must never produce (`allow`, `deny`), so T1 is a real theorem and not just true by the type.

| # | Name (Lean) | Statement |
| --- | --- | --- |
| T1 | `never_allows` | `hook` never returns `allow` or `deny`; only `none` or `ask r`. |
| T2 | `config_error_asks` | Config error (bad `GATE_STRICT`/`GATE_ENABLED` value, unknown id in `GATE_DISABLE_RULES`, bad rules file) with the gate enabled → `ask gateConfig`, whatever the input and Jev say. |
| T3 | `input_error_asks` | Input-level failure (stdin not JSON, no `tool_name`, Bash call without `command`) → `ask unparsable`; the Jev answer and settings are irrelevant. |
| T4 | `jev_config_error_asks` | Jev on, Jev config invalid, rule result not closed → `ask gateConfig`, even when the rules had no opinion. |
| T5 | `jev_inert_keeps_rules` | Jev off, call kind outside `GATE_JEV_SCOPE`, request failed, or answer in the uncertain band → final = rule result. |
| T6 | `jev_escalates` | In scope, rule result not closed, `risk > escalate` → `ask jev`, whatever the rule result and `canLift`. |
| T7 | `no_lift_only_adds` | `canLift = false` → a rule `ask` is never turned into `none`. |
| T8 | `lift_is_only_way_out` | Rule result `ask r` and final `none` ⇒ Jev on and valid, in scope, `r` not closed, `risk ≤ escalate`, `safe ≥ allow`, `canLift`. This states that Jev can lift a strict-mode `unparsable` command ask (`commandUnparsable`). That's by design, and the theorem makes it explicit. |
| T9 | `strict_monotone` | Everything else equal, `strict = false` gives `ask` ⇒ `strict = true` gives `ask`. |
| T10 | `lenient_parse_failure_is_silent` | `strict = false` and the command string as a whole fails to parse ⇒ rule result `none`. Pins a known weakness (see Non-theses) so it cannot change silently. |
| T11 | `more_rules_monotone` / `disable_antitone` | Adding a rule to the `rules` array never turns `ask` into `none`. Adding an id to the disable set never turns `none` into `ask`, and the ask reason is never a disabled id. |
| T12 | `first_ask_wins` | Rule result = ask of the first part (in command order) that some enabled rule asks for; rule ask reason = that rule's id. With `strict = true`, a part that fails to parse before it gives `ask unparsable`. |
| T13 | `wrapper_fail_closed` | `gate.sh` gives empty stdout only if `GATE_ENABLED` is an off value, or the engine exited 0, wrote the done-file and printed nothing. rc 126/127 → `ask unparsable` (interpreter unavailable); other failures → `ask gateConfig`. |

### Non-theses (written down so nobody assumes them)

- **Pack monotonicity in general is false.** `composeRules` merges `wrappers`, `inertPrograms` and `inertUnsafeFlags` from every pack, and these lists can make the gate ask less. T11 covers only the `rules` array. Task 2 adds a docstring with a minimal counterexample (a second pack that adds a program to `inertPrograms`); prove it in Lean only if it costs less than an hour.
- **The parser matches bash.** Not modelled. The model takes the parse result as an input. A bypass needs a command that bash runs but the parser rejects (silently allowed under T10) or reads differently. That belongs to a separate bash-differential test plan.
- **The script scan.** Modelled as an input (`none | ask id | error`). The oracle generator never produces script files, so the scan always returns `none` in the differential test.
- **Float ties at Jev thresholds.** The model uses per-mille naturals with exact arithmetic. JS/Python compare floats, so the generator never produces `risk = escalate` or `safe = allow` (see Review Focus).

## Global Constraints

- Lean 4 core + Lake only; no Mathlib or Batteries (keeps the CI build under ~2 min). Pin the toolchain in `formal/destructive-guard/lean-toolchain` to the latest stable `leanprover/lean4:v4.X.Y` reported by `elan` at execution time.
- No `sorry`, `admit` or `axiom` in `formal/`. The check is `! grep -rnE '\b(sorry|admit|axiom)\b' formal/destructive-guard/GateModel formal/destructive-guard/Oracle`, and `lake build` must print no `declaration uses 'sorry'` warning.
- Every theorem in the table has exactly that Lean name in `GateModel/Theorems.lean` and a docstring citing the JS function it models.
- No change to `plugins/**` code, packs or prompts. This package adds tests and docs only. `node --test` and `uv run pytest` stay green with unchanged counts, apart from the new test file.
- Public repo hygiene (`CLAUDE.md`): fictional programs `tool0`…`tool3`, MCP tool `mcp__tracker__editIssue`, placeholder ticket `PROJ-1`.
- The differential test passes with `GD_IMPL=js`. Locally it skips when `gate-oracle` is not built, and `REQUIRE_ORACLE=1` turns that skip into a failure (CI sets it).

## Review Focus

- Jev probabilities exactly at a threshold: exact vs float arithmetic can disagree. The generator rejects ties; `test_oracle_rejects_ties` (Task 4) pins that the generator never emits one.
- Jev mock request failures: a 5xx answer may be retried with backoff (`retryDelay`) and slow the suite. The concretizer uses `kind="malformed"` for "request failed"; `test_failed_request_is_fast` asserts one scenario completes in < 3 s.
- `GATE_JEV=0` is truthy in `applyJev` but `readJevConfig` returns null. The model must treat `"0"` as off, not as a config error. Oracle golden case in Task 3.
- `GATE_DISABLE_RULES` with an id that is not in the rules file → `gate-config` ask, not silently ignored. The generator draws 10% of scenarios with one unknown id.
- A developer's exported `GATE_*`/`TYPESAFE_*` must not leak into scenarios. All env goes through `clean_env` (`run_hook` already does this); `test_scenarios_env_is_complete` asserts each concretized env sets `GATE_STRICT`, `GATE_CHECKS`, `GATE_RULES_FILE` and `GATE_JEV` explicitly.

---

### Task 1: Lake project and the model

**Files:**
- Create: `formal/destructive-guard/lean-toolchain`, `formal/destructive-guard/lakefile.toml`, `formal/destructive-guard/GateModel.lean` (imports all modules), `formal/destructive-guard/GateModel/Decision.lean`, `GateModel/Classify.lean`, `GateModel/Jev.lean`, `GateModel/Hook.lean`, `GateModel/Examples.lean`
- Modify: `.gitignore` (add `formal/**/.lake/`)

**Interfaces (Produces):**
- `Decision.lean`: `inductive Reason | gateConfig | unparsable (commandLevel : Bool) | rule (id : Nat) | jev`; `def Reason.closed : Reason → Bool` (true for `gateConfig` and `unparsable false`); `inductive Out | none | ask (r : Reason) | allow | deny`; `abbrev RuleResult := Option Reason` (`none` = no opinion).
- `Classify.lean`: `structure RuleSet where rules : List Nat; disabled : List Nat`. A part is `Option Nat` (the program index, or `none` = this part failed to parse). `def classify (strict : Bool) (cmd : Option (List (Option Nat))) (rs : RuleSet) : RuleResult`, where `cmd = none` means the whole command string failed to parse. Rule `i` asks for part `some p` iff `p = i`, `i ∈ rules` and `i ∉ disabled`. This mirrors the fixture rules `{"id": "r<i>", "kind": "cli-gated", "programs": ["tool<i>"], "gatedPrefixes": [[]]}`. Semantics from `classifyInner`: strict + `cmd = none` → `unparsable true`. Strict: walk the parts in order; a failed part → `unparsable true`, a part with an ask → `rule i`. Lenient: `cmd = none` → `none`, failed parts are skipped.
- `Jev.lean`: `structure JevCfg where scopeBash scopeMcp canLift : Bool; escalate allowT : Nat` (per mille). `inductive JevSetting | off | invalid | on (c : JevCfg)`. `inductive JevAnswer | failed | probs (risk safe : Nat)`. `def jevDecision (c : JevCfg) (risk safe : Nat) : Option Bool`: `some true` = ask when `risk > escalate`, else `some false` = pass when `safe ≥ allowT`, else `none`. `def applyJev (s : JevSetting) (isBash : Bool) (r : RuleResult) (a : JevAnswer) : Out` mirrors `applyJev` + `runJev`, in the order of the JS checks.
- `Hook.lean`: `inductive Input | bash (cmd : Option (List (Option Nat))) | mcp | badJson | noTool | noCommand`; `inductive Scan | none | ask (id : Nat) | error`. `structure Scenario where enabled configOk strict : Bool; rs : RuleSet; input : Input; scan : Scan; jev : JevSetting; answer : JevAnswer`. `def engine (s : Scenario) : Out` mirrors `main` + `gate`: config check first, then input, then classify, then the scan (Bash only, not closed, when the result is `none` or Jev is not off; a scan error → `gateConfig`), then `applyJev`. `configOk` already folds in "unknown disabled id"; the oracle computes it as `disabled ⊆ rules ∧ strictValid`. `def wrapper (envOff : Bool) (rc : Nat) (done : Bool) (out : Out) : Out` mirrors `gate.sh`. `def hook (envOff : Bool) (rc : Nat) (done : Bool) (s : Scenario) : Out := wrapper envOff rc done (engine s)`.

- [ ] **Step 1: Write the example checks** in `GateModel/Examples.lean`, one `example : … := by decide` (or `rfl`) per case probed from the JS on 2026-11-20 through `check --json`:
  - parts `[2, 1]`, rules `[0, 1]`, both strict values → `ask (rule 1)`
  - parts `[1]` + whole-command parse failure: strict → `ask (unparsable true)`, lenient → `none`
  - parts `[0, 1]`, disabled `[0]` → `ask (rule 1)`
  - parts `[2]` → `none`
  - plus `jevDecision {escalate := 500, allowT := 950, ..} 600 400 = some true` and `… 30 970 = some false` and `… 300 700 = none`
- [ ] **Step 2:** `cd formal/destructive-guard && lake build` → fails (modules missing).
- [ ] **Step 3:** Implement the interfaces above. Use plain structural recursion, `List.find?` and `List.elem`, so `decide` works on the examples.
- [ ] **Step 4:** `lake build` → succeeds with no warnings.

### Task 2: The theorems

**Files:** Create `formal/destructive-guard/GateModel/Theorems.lean` (imported by `GateModel.lean`), `formal/destructive-guard/scripts/check-proofs.sh`.

**Interfaces:** Consumes everything in Task 1. Produces the theorem names in the Theses table. Statement shapes, quantified over every argument not named:
- `never_allows : hook e rc d s ≠ .allow ∧ hook e rc d s ≠ .deny`
- `config_error_asks : s.enabled → !s.configOk → engine s = .ask .gateConfig`
- `jev_escalates : s.enabled → s.configOk → s.jev = .on c → inScope c s.input → (∀ r, ruleOf s = some r → !r.closed) → s.scan ≠ .error → s.answer = .probs risk safe → risk > c.escalate → engine s = .ask .jev` (helpers `ruleOf : Scenario → RuleResult`, the classify + scan result before Jev, and `inScope : JevCfg → Input → Bool`, both defined in `Hook.lean` and reused by `engine`)
- `lift_is_only_way_out : ruleOf s = some r → engine s = .none → ∃ c risk safe, s.jev = .on c ∧ inScope c s.input ∧ !r.closed ∧ s.answer = .probs risk safe ∧ risk ≤ c.escalate ∧ safe ≥ c.allowT ∧ c.canLift`
- `strict_monotone`, `more_rules_monotone`, `disable_antitone` state their claims about `classify`. T9 and T11 also get an `engine`-level corollary with Jev `off`.
- `wrapper_fail_closed : hook e rc d s = .none → e ∨ (rc = 0 ∧ d ∧ engine s = .none)`

`check-proofs.sh`: runs `lake build` and fails if the output contains `sorry`, then runs the `grep` from Global Constraints.

- [ ] **Step 1:** Write all 13 theorem statements (T11 is two) with `:= by sorry` and docstrings that cite the JS function and line range.
- [ ] **Step 2:** `bash formal/destructive-guard/scripts/check-proofs.sh` → exits non-zero and names the `sorry` declarations.
- [ ] **Step 3:** Prove them. Prove the `classify` lemmas by induction on the part list. Prove the `engine`/`applyJev` ones by `unfold` + `split` / `cases` over the inputs, then `simp_all` / `omega`.
- [ ] **Step 4:** `check-proofs.sh` → exits 0.
- [ ] **Step 5: Mutation sanity check (not committed).** Change `applyJev` to ignore `canLift`, and `T7` must fail to build. Change lenient `classify` to skip only failed parts, not a failed whole command, and `T10` must fail. Revert both and record in the report that they failed as expected.

### Task 3: The oracle executable

**Files:** Create `formal/destructive-guard/Oracle/Main.lean`, `formal/destructive-guard/test/oracle-golden.in.jsonl`, `formal/destructive-guard/test/oracle-golden.out.jsonl`. Modify `lakefile.toml` (`[[lean_exe]] name = "gate-oracle" root = "Oracle.Main"`).

**Interfaces (Produces):** the scenario wire format, one JSON object per line on stdin:

```json
{"enabled": true, "strict_raw": "0", "rules": [0, 1], "disabled": [],
 "input": {"kind": "bash", "parts": [2, 1], "parse_ok": true},
 "jev": null | "invalid" | {"bash": true, "mcp": true, "can_lift": true,
          "escalate": 500, "allow": 950,
          "answer": "failed" | {"risk": 600, "safe": 400}}}
```

`input.kind` ∈ `bash | mcp | bad-json | no-tool | no-command`. `strict_raw` ∈ `"0" | "1" | "maybe"` (`"maybe"` → config error). Output, one line per input: `{"decision": "none"}` or `{"decision": "ask", "id": "gate-config" | "unparsable" | "r<i>" | "jev"}`. The scan is always `none` and the wrapper is always `rc = 0, done = true`, since the differential test exercises those paths through P1's fake-engine tests instead.

- [ ] **Step 1:** Write the golden input: the 4 Task 1 rule cases, `strict_raw: "maybe"`, unknown disabled id `[7]`, `bad-json`, a lenient parse failure with Jev confident-safe and `can_lift: false`, `jev: "invalid"` over a `none` rule result, and Jev on with `"answer": "failed"`. Write the expected output by hand from the Theses table.
- [ ] **Step 2:** `lake build gate-oracle && lake exe gate-oracle < test/oracle-golden.in.jsonl | diff - test/oracle-golden.out.jsonl` → fails (no exe).
- [ ] **Step 3:** Implement `main`: parse each line with `Lean.Json.parse`, map it to `Scenario` (`configOk := strict_raw ∈ ["0","1"] ∧ disabled ⊆ rules`, `isBash := kind = "bash"`), print `hook false 0 true s`. A line that fails to parse → print `{"error": "<msg>"}` and exit 2.
- [ ] **Step 4:** Rerun the diff → empty.

### Task 4: Differential test against the real hook

**Files:** Create `testkit/scenarios.py`, `plugins/destructive-guard/tests/test_lean_oracle.py`, `tests/test_testkit_scenarios.py`.

**Interfaces:**
- Consumes: `testkit.hook.run_hook`, `bash_input`, `mcp_input`, `decision`; `testkit.jev_mock.JevMock`, `probs`; `testkit.projects.temp_project`; the `impl` and `jev` fixtures.
- Produces:
  - `testkit.scenarios.generate(seed: int, n: int) -> list[dict]` returns scenarios in the Task 3 wire format: 1–4 parts drawn from `0..3`, rules a random subset of `0..3`, `disabled ⊆ rules` except in 10% of scenarios (one unknown id `7`), 15% `parse_ok: false`, 10% non-bash input kinds, 5% `strict_raw: "maybe"`, Jev `null` 30% / `"invalid"` 5% / on 65%. Probabilities are per mille: `risk + safe = 1000`, and ties with `escalate`/`allow` are rejected. `escalate ∈ {300, 500, 700}`, `allow ∈ {800, 950}`.
  - `testkit.scenarios.concretize(s: dict, project: Path, rules_path: Path, jev_url: str) -> Concrete`, where `Concrete = (stdin: str, env: dict[str, str], jev_answer: dict | None)` (a `NamedTuple`). Rules file `{"rules": [{"id": "r<i>", "kind": "cli-gated", "programs": ["tool<i>"], "gatedPrefixes": [[]]} …]}`. Command `" && ".join(f"tool{p} x" …)`, plus `"; echo 'x"` when `parse_ok` is false. Inputs: `mcp` → `mcp_input("mcp__tracker__editIssue", {"issue": "PROJ-1"}, project)`; `bad-json` → `"{"`; `no-tool` → `'{"tool_input": {}}'`; `no-command` → `'{"tool_name": "Bash", "tool_input": {}}'`. Env: `GATE_CHECKS=none`, `GATE_RULES_FILE=<rules_path>`, `GATE_STRICT=<strict_raw>`, `GATE_DISABLE_RULES=",".join(f"r{i}")` (or empty), `CLAUDE_PROJECT_DIR=<project>`. Jev on adds `GATE_JEV=1`, `TYPESAFE_API_KEY=test-key`, `GATE_JEV_URL=<jev_url>`, `GATE_JEV_PROMPT=cloud-change`, `GATE_JEV_TIMEOUT_MS=5000`, `GATE_JEV_SCOPE` from the two flags (`bash,mcp` / `bash` / `mcp`; generate at least one), `GATE_JEV_CAN_LIFT=1|0`, and both thresholds as `f"{x/1000:.3f}"`. Jev invalid → `GATE_JEV=1` without `TYPESAFE_API_KEY`. Jev answer: `probs(unrelated=safe/2000, read_only=safe/2000, cloud_or_data_change=risk/1000, destructive=0)` (in `cloud-change`, `ask = [cloud_or_data_change, destructive]` and `safe = [unrelated, read_only]`), or `{"kind": "malformed"}` when failed.
  - `testkit.scenarios.oracle(scenarios: list[dict]) -> list[dict]` runs `formal/destructive-guard/.lake/build/bin/gate-oracle` once with all lines; `ORACLE_BIN` overrides the path.
  - `testkit.scenarios.outcome(stdout: str) -> dict`: `{"decision": "none"}` for empty stdout, else `{"decision": "ask", "id": reason.split(":")[0]}`.

- [ ] **Step 1: Tests.** In `tests/test_testkit_scenarios.py`: `test_generate_is_deterministic` (same seed → same list), `test_oracle_rejects_ties` (10 000 generated scenarios with Jev on never have `risk == escalate` or `safe == allow`), `test_scenarios_env_is_complete`, `test_concretize_command_shape` (parts `[2, 1]`, `parse_ok: false` → `tool2 x && tool1 x; echo 'x`). In `plugins/destructive-guard/tests/test_lean_oracle.py`: `test_hook_matches_oracle` (seed from `ORACLE_SEED`, default `20261120`; `n` from `ORACLE_N`, default `120`; a mismatch prints the scenario, the concrete stdin/env and both outcomes, and the assertion message lists every mismatch, not just the first), `test_failed_request_is_fast`. The module skips when the oracle binary is missing unless `REQUIRE_ORACLE=1`.
- [ ] **Step 2:** `uv run pytest tests/test_testkit_scenarios.py plugins/destructive-guard/tests/test_lean_oracle.py -v` → fails (module missing).
- [ ] **Step 3:** Implement the `testkit/scenarios.py` interfaces. Use one `JevMock` for the whole run and run scenarios sequentially, calling `jev.answer(...)` before each one.
- [ ] **Step 4:** Build the oracle, then `REQUIRE_ORACLE=1 uv run pytest tests/test_testkit_scenarios.py plugins/destructive-guard/tests/test_lean_oracle.py -v` → pass. Then `ORACLE_N=1000` once locally → pass; put the wall time in the report. A mismatch means the model or the code is wrong: stop and report the scenario, don't change the generator to dodge it.

### Task 5: CI, docs, commit

**Files:** Modify `.github/workflows/test.yml`, `CLAUDE.md` (Test and validate section), `docs/plans/python-port.md` (P5/P7/P8 note: "the Lean oracle test must stay green"). Create `formal/destructive-guard/README.md`.

- [ ] **Step 1: CI.** Add a `lean` job: checkout, install elan (`curl -sSf https://raw.githubusercontent.com/leanprover/elan/master/elan-init.sh | sh -s -- -y --default-toolchain none`), cache `~/.elan` and `formal/destructive-guard/.lake`, run `scripts/check-proofs.sh`, `lake build gate-oracle`, the golden diff, and upload `.lake/build/bin/gate-oracle` as an artifact. The `python` job adds `needs: lean`, downloads the artifact, `chmod +x`, and sets `ORACLE_BIN` and `REQUIRE_ORACLE=1`.
- [ ] **Step 2: README.** `formal/destructive-guard/README.md`: what is modelled and what isn't (copy the Theses and Non-theses tables, each row linked to its Lean name), build/run commands, and the rule "a behaviour change to the decision core updates the model, the theorems and the golden file in the same commit". In `CLAUDE.md`, add three lines under Test and validate: `formal/destructive-guard/scripts/check-proofs.sh`, `lake build gate-oracle` (in `formal/destructive-guard`), `REQUIRE_ORACLE=1 uv run pytest plugins/destructive-guard/tests/test_lean_oracle.py`.
- [ ] **Step 3: Full verification.** `bash formal/destructive-guard/scripts/check-proofs.sh`, `node --test 'plugins/destructive-guard/test/*.test.mjs'`, `REQUIRE_ORACLE=1 uv run pytest`, `uv run ruff check .`, `claude plugin validate .` → all green. Plugin versions are not bumped because no plugin file changed.
- [ ] **Step 4: Commit** (one commit for the package):

```bash
git add formal/ testkit/scenarios.py tests/test_testkit_scenarios.py \
  plugins/destructive-guard/tests/test_lean_oracle.py .github/workflows/test.yml \
  .gitignore CLAUDE.md docs/plans/python-port.md docs/plans/lean-gate-model.md
git commit -m "destructive-guard: Lean model of the decision core + oracle test"
```
