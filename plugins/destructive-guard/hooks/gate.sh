#!/usr/bin/env bash
# PreToolUse approval gate wrapper. Fails closed: allow (empty stdout, exit 0)
# is only emitted when the engine proved it ran to completion via a done-file.
dir="$(dirname "$0")"
ask() {
  printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"ask","permissionDecisionReason":"%s"}}' "$1"
  exit 0
}
done_file="$(mktemp 2>/dev/null)" || ask "gate-config: engine failed"
trap 'rm -f "$done_file"' EXIT
rm -f "$done_file"
out="$(GATE_RUN=1 GATE_DONE_FILE="$done_file" "${GATE_INFRA_NODE:-node}" "$dir/../lib/gate-engine.mjs" 2>/dev/null)"
rc=$?
[ "$rc" -eq 127 ] || [ "$rc" -eq 126 ] && ask "unparsable: node unavailable"
[ "$rc" -ne 0 ] && ask "gate-config: engine failed"
[ -f "$done_file" ] || ask "gate-config: engine failed"
[ -n "$out" ] && printf '%s' "$out"
exit 0
