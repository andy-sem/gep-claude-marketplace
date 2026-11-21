#!/usr/bin/env bash
# PreToolUse approval gate wrapper. Fails closed: allow (empty stdout, exit 0)
# is only emitted when the engine proved it ran to completion via a done-file.
dir="$(dirname "$0")"
# GATE_ENABLED=0 turns the gate off without starting python; any other value is
# validated by the engine (an invalid one asks).
case "$(printf '%s' "${GATE_ENABLED:-}" | tr '[:upper:]' '[:lower:]')" in
  0|false|no|off) exit 0 ;;
esac
ask() {
  printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"ask","permissionDecisionReason":"%s"}}' "$1"
  exit 0
}
# Interpreter: GATE_INFRA_PYTHON if set (a broken one asks, no fallback), else
# python3.14, else python3. Always -I (isolated: ignores PYTHONPATH, user site
# and the current directory). A too-old Python exits 3 from the entry stub.
py="${GATE_INFRA_PYTHON:-}"
[ -n "$py" ] || py="$(command -v python3.14 || command -v python3)"
[ -n "$py" ] || ask "unparsable: python unavailable"
done_file="$(mktemp 2>/dev/null)" || ask "gate-config: engine failed"
trap 'rm -f "$done_file"' EXIT
rm -f "$done_file"
out="$(GATE_RUN=1 GATE_DONE_FILE="$done_file" "$py" -I "$dir/../lib/gate_main.py" 2>/dev/null)"
rc=$?
{ [ "$rc" -eq 127 ] || [ "$rc" -eq 126 ] || [ "$rc" -eq 3 ]; } && ask "unparsable: python unavailable"
[ "$rc" -ne 0 ] && ask "gate-config: engine failed"
[ -f "$done_file" ] || ask "gate-config: engine failed"
[ -n "$out" ] && printf '%s' "$out"
exit 0
