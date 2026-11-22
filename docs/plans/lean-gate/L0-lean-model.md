# L0: Lean model matches the decisions; Claude Code assumptions checked

> Part of the [lean gate plan](README.md). Depends on: nothing. Needs: D2, D3, D11, D12 (all answered 2026-11-22).

Files: `formal/SimpleGate.lean`, `formal/README` note in the plugin README.

1. `Setting`: remove `off` (D2). `Setting = misconfigured | on`.
2. `Down`: remove `off` and `misconfigured` (misconfigured gives no warning per
   call); add `network`, `pythonMissing` and `internalError`. Result:
   `timeout | http | network | malformed | envReference | badInput | pythonMissing | internalError`.
   New predicate `Down.jevUnavailable : Down → Bool`, true for `timeout`,
   `http`, `network`, `malformed`.
2a. `JevResult.down` carries Jev failures (`jevUnavailable`) and plugin faults
   (`badInput`, `pythonMissing`, `internalError`). `judge c (.down why) =
   ⟨.ask, some why⟩` for all of them (D11, D12). Only the `.env` skip
   (`envReference`) stays `⟨.none, some why⟩`.
3. `Call`: add `pythonMissing` and `crash` alongside `tool p` and `badInput`,
   so the wrapper's and the exception path's outputs are part of `hook`:
   `.badInput → ⟨ask, some .badInput⟩`,
   `.pythonMissing → ⟨ask, some .pythonMissing⟩`,
   `.crash → ⟨ask, some .internalError⟩` (D12).
4. `hook … .misconfigured (.tool p) = ⟨.none, none⟩` (D3).
5. New `SessionIssue` (`noKey | badUrl | badPrompt | badValue | pythonMissing`)
   and `sessionStart : Setting → Option SessionIssue`, with the setting
   carrying the issue (`misconfigured (why : SessionIssue)`). New thesis
   **S9** `misconfigured_warns_once`: `sessionStart s = some w ↔ s = .misconfigured w`,
   and `hook` for `.misconfigured _` never warns.
6. Theses after D11:
   - **S2** `asks_iff`: ask ⇔ on ∧ ((Jev answered with `risk > escalate`) ∨
     Jev was unavailable ∨ plugin fault: bad input, no Python, internal error).
     A `.env` call never asks.
   - **S3** `warning_decision`: a warning comes with `ask` iff its reason is
     `jevUnavailable` or `pluginFault`; the `.env` warning and misconfigured
     have no decision.
   - **S4** `fallback_is_claude`: premise narrowed to the `.env` warning and
     misconfigured; there the final permission is exactly Claude Code's.
   - **S10** (new) `unavailable_asks`: on ∧ sent ∧ Jev down ⇒ ask with a
     warning, i.e. an unreachable Jev never silently lets a call through.
   - **S8** unchanged (an answer never warns); S1, S5, S6, S7 re-proved
     unchanged (an `ask` is never weaker than Claude Code's own permission).
7. Examples at the bottom extended to one per row of the conformance table in
   L1 (`.misconfigured`, `.pythonMissing`, `.crash`, `.envReference`, risk 0,
   risk = 500, risk 501, each `Down`).
8. **D7 check.** Read the current Claude Code hooks docs (PreToolUse output:
   `permissionDecision`, `systemMessage`; SessionStart output) and record, with
   links and the Claude Code version (`claude --version`):
   - a hook `ask` prompts even when a settings `allow` rule matches;
   - a settings `deny` wins over a hook `ask`;
   - no hook output leaves the call to rules and mode;
   - behaviour under `bypassPermissions` and auto mode;
   - `systemMessage` from PreToolUse and SessionStart is shown to the user;
   - a PreToolUse output may carry both `systemMessage` and
     `hookSpecificOutput.permissionDecision: "ask"` and both take effect (D11).
   Confirm with a throwaway plugin in the scratchpad (hook that always prints
   `ask`, or only a `systemMessage`) against an allow rule, a deny rule,
   bypass mode and auto mode. If an assumption is false, stop and bring it to
   the user: S4/S5 depend on it.
9. `lake build --wfail`: no errors, warnings or `sorry`.

Commit: `Lean gate L0: model with session warning, D2/D3 applied, CC assumptions checked`.

## Done when

- [ ] `uv run pytest` and `uv run ruff check .` pass
- [ ] `claude plugin validate .` and `jq . .claude-plugin/marketplace.json` pass
- [ ] `cd plugins/destructive-guard/formal && PATH="$HOME/.elan/bin:$PATH" lake build --wfail` passes
- [ ] one commit with the message given above; nothing pushed unless asked
