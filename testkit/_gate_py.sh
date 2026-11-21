#!/usr/bin/env bash
# Test-only copy of hooks/gate.sh that starts the Python engine (D1a lookup, -I).
# Lets the hook contract tests run on Python before gate.sh itself switches (P9).
dir="$(dirname "$0")/../plugins/destructive-guard/hooks"
case "$(printf '%s' "${GATE_ENABLED:-}" | tr '[:upper:]' '[:lower:]')" in
  0|false|no|off) exit 0 ;;
esac
ask() {
  printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"ask","permissionDecisionReason":"%s"}}' "$1"
  exit 0
}
py="${GATE_INFRA_PYTHON:-}"
[ -n "$py" ] || py="$(command -v python3.14 || command -v python3)"
[ -n "$py" ] || ask "unparsable: python unavailable"
done_file="$(mktemp 2>/dev/null)" || ask "gate-config: engine failed"
trap 'rm -f "$done_file"' EXIT
rm -f "$done_file"
out="$(GATE_RUN=1 GATE_DONE_FILE="$done_file" "$py" -I "$dir/../lib/gate_main.py" 2>/dev/null)"
rc=$?
[ "$rc" -eq 127 ] || [ "$rc" -eq 126 ] || [ "$rc" -eq 3 ] && ask "unparsable: python unavailable"
[ "$rc" -ne 0 ] && ask "gate-config: engine failed"
[ -f "$done_file" ] || ask "gate-config: engine failed"
[ -n "$out" ] && printf '%s' "$out"
exit 0
