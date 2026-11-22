#!/usr/bin/env bash
# SessionStart: runs the one-time configuration warning (lib/session_main.py). Prints a systemMessage
# or nothing; it never decides anything. This is where a missing Python is reported once.
dir="$(dirname "$0")"
case "$(printf '%s' "${GATE_ENABLED:-}" | tr '[:upper:]' '[:lower:]')" in
  0|false|no|off) exit 0 ;;
esac
warn() {
  printf '{"systemMessage":"destructive-guard: %s"}' "$1"
  exit 0
}
no_python="no Python >= 3.14 found (set GATE_INFRA_PYTHON): every Bash and MCP call will ask this session; GATE_ENABLED=0 turns the gate off"
py="${GATE_INFRA_PYTHON:-}"
[ -n "$py" ] || py="$(command -v python3.14 || command -v python3)"
[ -n "$py" ] || warn "$no_python"
out="$("$py" -I "$dir/../lib/session_main.py" 2>/dev/null)"
rc=$?
{ [ "$rc" -eq 127 ] || [ "$rc" -eq 126 ] || [ "$rc" -eq 3 ]; } && warn "$no_python"
[ "$rc" -eq 0 ] && [ -n "$out" ] && printf '%s' "$out"
exit 0
