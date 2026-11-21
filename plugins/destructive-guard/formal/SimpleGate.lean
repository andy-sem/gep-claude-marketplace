/-!
# Simple gate: Jev decides, otherwise Claude Code decides

Model of the proposed lean `destructive-guard`:

1. call → Jev → risky: `ask` (a person approves or denies, then Claude Code's
   own permissions apply) / not risky: no decision (Claude Code's own logic).
2. call → Jev off, misconfigured or down → no decision plus a warning
   (`systemMessage`), so Claude Code's own logic applies.

No rule packs, no shell parser, no fail-closed asks. Calls that mention a
`.env` file are never sent to Jev; everything else is redacted before sending.

## Theses (all proved below)

| # | Name | Statement |
|---|------|-----------|
| S1 | `never_allows` | The hook never returns `allow` or `deny`. |
| S2 | `asks_iff` | The hook asks **iff** Jev is on, the call was sent (no `.env` reference) and Jev answered with `risk > escalate`. |
| S3 | `warning_means_no_decision` | Whenever a warning is shown, the hook makes no decision. |
| S4 | `fallback_is_claude` | With a warning (Jev off/down/misconfigured, bad input, `.env` skip) the final permission is exactly Claude Code's own. |
| S5 | `never_weaker` | The final permission is never weaker than Claude Code's own (allow < ask < deny): the plugin can only add prompts. |
| S6 | `threshold_monotone` | Lowering `escalate` never removes an ask. |
| S7 | `sees_only_redacted` | The outcome depends on Jev only through redacted payloads that mention no `.env` file. |
| S8 | `answer_no_warning` | A Jev answer never shows a warning. |

## Assumptions about Claude Code (not proved, check against the docs of the version in use)

* A hook `ask` makes Claude Code prompt even when a settings rule allows the
  call; a settings `deny` still wins (`effective`).
* No hook decision leaves the call to Claude Code's permission rules and mode;
  `bypassPermissions` is modelled as Claude's own permission being `allow`.
-/

namespace SimpleGate

/-- Why there is no Jev answer. Each one is shown as a warning. -/
inductive Down where
  | off | misconfigured | timeout | http | malformed | envReference | badInput
  deriving DecidableEq, Repr

/-- What the Jev request returned. `risk` is the per-mille sum of the prompt's
ask choices (e.g. `cloud_or_data_change + destructive`). -/
inductive JevResult where
  | down (why : Down)
  | answer (risk : Nat)
  deriving DecidableEq, Repr

/-- `GATE_JEV`: unset/0, set but invalid (no API key, bad URL), or on. -/
inductive Setting where
  | off | misconfigured | on
  deriving DecidableEq, Repr

/-- `GATE_JEV_ESCALATE_THRESHOLD` in per mille. -/
structure Config where
  escalate : Nat := 500
  deriving Repr

/-- The hook protocol's decisions. `allow` and `deny` exist so that S1 says
something: the gate could print them, it just never does. -/
inductive HookDecision where
  | none | ask | allow | deny
  deriving DecidableEq, Repr

/-- What the hook prints: a decision and an optional warning (`systemMessage`). -/
structure HookOut where
  decision : HookDecision
  warning : Option Down
  deriving DecidableEq, Repr

/-- A Bash command or MCP call (its text as sent to Jev), or hook stdin that
could not be read. -/
inductive Call where
  | tool (payload : String)
  | badInput
  deriving DecidableEq, Repr

/-- The redactor and the `.env` detector, left abstract. -/
structure Env where
  redact : String → String
  mentionsEnv : String → Bool

/-- Jev's answer → hook output. The uncertain band and a safe answer both give
no decision: with no rules there is nothing to lift or fall back to. -/
def judge (c : Config) : JevResult → HookOut
  | .down why => ⟨.none, some why⟩
  | .answer risk => if c.escalate < risk then ⟨.ask, none⟩ else ⟨.none, none⟩

/-- The whole hook. `q` is the Jev request. -/
def hook (e : Env) (c : Config) (s : Setting) (q : String → JevResult) : Call → HookOut
  | .badInput => ⟨.none, some .badInput⟩
  | .tool p =>
    match s with
    | .off => ⟨.none, some .off⟩
    | .misconfigured => ⟨.none, some .misconfigured⟩
    | .on =>
      if e.mentionsEnv p = true then ⟨.none, some .envReference⟩
      else judge c (q (e.redact p))

/-! ## Claude Code's side -/

/-- Claude Code's own permission for a call (settings rules + mode). -/
inductive Perm where
  | allow | ask | deny
  deriving DecidableEq, Repr

def rank : Perm → Nat
  | .allow => 0
  | .ask => 1
  | .deny => 2

/-- Final permission: hook decision on top of Claude Code's own. -/
def effective : HookDecision → Perm → Perm
  | .none, p => p
  | .ask, .deny => .deny
  | .ask, _ => .ask
  | .allow, .deny => .deny
  | .allow, _ => .allow
  | .deny, _ => .deny

/-! ## Lemmas about `judge` -/

theorem judge_not_allow (c : Config) (r : JevResult) :
    (judge c r).decision ≠ .allow ∧ (judge c r).decision ≠ .deny := by
  cases r with
  | down w => simp [judge]
  | answer k =>
    by_cases h : c.escalate < k <;> simp [judge, h]

theorem judge_ask (c : Config) (r : JevResult) :
    (judge c r).decision = .ask ↔ ∃ k, r = .answer k ∧ c.escalate < k := by
  cases r with
  | down w => simp [judge]
  | answer k =>
    by_cases h : c.escalate < k <;> simp [judge, h]

theorem judge_warning (c : Config) (r : JevResult) :
    (judge c r).warning.isSome = true → (judge c r).decision = .none := by
  cases r with
  | down w => simp [judge]
  | answer k =>
    by_cases h : c.escalate < k <;> simp [judge, h]

/-! ## Theses -/

/-- S1 -/
theorem never_allows (e : Env) (c : Config) (s : Setting) (q : String → JevResult)
    (call : Call) :
    (hook e c s q call).decision ≠ .allow ∧ (hook e c s q call).decision ≠ .deny := by
  cases call with
  | badInput => simp [hook]
  | tool p =>
    cases s with
    | off => simp [hook]
    | misconfigured => simp [hook]
    | on =>
      by_cases hm : e.mentionsEnv p = true
      · simp [hook, hm]
      · simp only [hook, hm]
        exact judge_not_allow c _

/-- S2: the only way to get a prompt from the plugin. -/
theorem asks_iff (e : Env) (c : Config) (s : Setting) (q : String → JevResult)
    (call : Call) :
    (hook e c s q call).decision = .ask ↔
      ∃ p, call = .tool p ∧ s = .on ∧ e.mentionsEnv p = false ∧
        ∃ r, q (e.redact p) = .answer r ∧ c.escalate < r := by
  cases call with
  | badInput => simp [hook]
  | tool p =>
    cases s with
    | off => simp [hook]
    | misconfigured => simp [hook]
    | on =>
      by_cases hm : e.mentionsEnv p = true
      · simp [hook, hm]
      · have hf : e.mentionsEnv p = false := by simpa using hm
        simp [hook, hf, judge_ask]

/-- S3 -/
theorem warning_means_no_decision (e : Env) (c : Config) (s : Setting)
    (q : String → JevResult) (call : Call) :
    (hook e c s q call).warning.isSome = true → (hook e c s q call).decision = .none := by
  cases call with
  | badInput => simp [hook]
  | tool p =>
    cases s with
    | off => simp [hook]
    | misconfigured => simp [hook]
    | on =>
      by_cases hm : e.mentionsEnv p = true
      · simp [hook, hm]
      · simp only [hook, hm]
        exact judge_warning c _

/-- S4: Jev off, down or misconfigured (and bad input, `.env` skip) leave the
call exactly to Claude Code. -/
theorem fallback_is_claude (e : Env) (c : Config) (s : Setting)
    (q : String → JevResult) (call : Call) (claude : Perm)
    (h : (hook e c s q call).warning.isSome = true) :
    effective (hook e c s q call).decision claude = claude := by
  rw [warning_means_no_decision e c s q call h]
  cases claude <;> rfl

theorem effective_monotone (d : HookDecision) (claude : Perm) (hd : d ≠ .allow) :
    rank claude ≤ rank (effective d claude) := by
  cases d <;> cases claude <;> simp_all [effective, rank]

/-- S5: the plugin only ever adds prompts. -/
theorem never_weaker (e : Env) (c : Config) (s : Setting) (q : String → JevResult)
    (call : Call) (claude : Perm) :
    rank claude ≤ rank (effective (hook e c s q call).decision claude) :=
  effective_monotone _ claude (never_allows e c s q call).1

/-- S6 -/
theorem threshold_monotone (e : Env) (c₁ c₂ : Config) (s : Setting)
    (q : String → JevResult) (call : Call) (h : c₂.escalate ≤ c₁.escalate) :
    (hook e c₁ s q call).decision = .ask → (hook e c₂ s q call).decision = .ask := by
  rw [asks_iff, asks_iff]
  rintro ⟨p, hc, hs, he, r, hq, hr⟩
  exact ⟨p, hc, hs, he, r, hq, Nat.lt_of_le_of_lt h hr⟩

/-- S7: two Jev endpoints that agree on every redacted, `.env`-free payload give
the same hook output, so nothing else can influence (or reach) Jev. -/
theorem sees_only_redacted (e : Env) (c : Config) (s : Setting)
    (q₁ q₂ : String → JevResult) (call : Call)
    (h : ∀ p, e.mentionsEnv p = false → q₁ (e.redact p) = q₂ (e.redact p)) :
    hook e c s q₁ call = hook e c s q₂ call := by
  cases call with
  | badInput => rfl
  | tool p =>
    cases s with
    | off => rfl
    | misconfigured => rfl
    | on =>
      by_cases hm : e.mentionsEnv p = true
      · simp [hook, hm]
      · have hf : e.mentionsEnv p = false := by simpa using hm
        simp only [hook, hm]
        rw [h p hf]

/-- S8 -/
theorem answer_no_warning (e : Env) (c : Config) (q : String → JevResult) (p : String)
    (k : Nat) (hm : e.mentionsEnv p = false) (hq : q (e.redact p) = .answer k) :
    (hook e c .on q (.tool p)).warning = none := by
  by_cases h : c.escalate < k <;> simp [hook, hm, hq, judge, h]

/-! ## Examples (default `escalate = 500`) -/

example : (judge {} (.answer 600)).decision = .ask := by decide
example : (judge {} (.answer 500)).decision = .none := by decide
example : (judge {} (.down .timeout)) = ⟨.none, some .timeout⟩ := by decide
example : effective .ask .allow = .ask := by decide
example : effective .none .allow = .allow := by decide

end SimpleGate
