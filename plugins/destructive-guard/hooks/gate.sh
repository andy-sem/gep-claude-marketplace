#!/usr/bin/env bash
# PreToolUse gate wrapper: prints the engine's stdout. It never allows or denies; on a plugin fault
# (no suitable Python, engine failed) it asks by itself, so it needs no Python for that.
dir="$(dirname "$0")"
# GATE_ENABLED=0 turns the gate off without starting python; any other value is validated by the engine.
case "$(printf '%s' "${GATE_ENABLED:-}" | tr '[:upper:]' '[:lower:]')" in
  0|false|no|off) exit 0 ;;
esac
fault() {
  printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"ask","permissionDecisionReason":"plugin-fault: %s"},"systemMessage":"destructive-guard: %s; asking you instead. GATE_ENABLED=0 turns the gate off."}' "$1" "$2"
  exit 0
}
no_python() { fault "no Python >= 3.14 found (set GATE_INFRA_PYTHON)" "no Python >= 3.14 found (set GATE_INFRA_PYTHON)"; }
# Interpreter: GATE_INFRA_PYTHON if set (a broken one is a fault, no fallback), else python3.14, else
# python3. Always -I (isolated: ignores PYTHONPATH, user site and the current directory). A too-old
# Python exits 3 from the entry stub.
py="${GATE_INFRA_PYTHON:-}"
[ -n "$py" ] || py="$(command -v python3.14 || command -v python3)"
[ -n "$py" ] || no_python
out="$("$py" -I "$dir/../lib/gate_main.py" 2>/dev/null)"
rc=$?
{ [ "$rc" -eq 127 ] || [ "$rc" -eq 126 ] || [ "$rc" -eq 3 ]; } && no_python
# A partial stdout of a failed engine is discarded: the fault ask replaces it.
[ "$rc" -ne 0 ] && fault "internal error: engine exit $rc" "internal error (engine exit $rc)"
[ -n "$out" ] && printf '%s' "$out"
exit 0
