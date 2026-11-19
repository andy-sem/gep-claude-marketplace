#!/usr/bin/env bash
# PreToolUse guard for Read/Edit/Write: blocks env files (exit 2): `.env`,
# `.env.*` and `*.env`, except `.env.example`. Matches the file name only, so
# `config.environment.ts` or a path through a `.env` directory are not blocked.
# Read is covered here because a plugin cannot ship permissions.deny entries.
# Off with GATE_ENABLED=0 or GATE_ENV_GUARD=0; other values keep it on.
off() {
  case "$(printf '%s' "${1:-}" | tr '[:upper:]' '[:lower:]')" in
    0|false|no|off) return 0 ;;
  esac
  return 1
}
off "${GATE_ENABLED:-}" && exit 0
off "${GATE_ENV_GUARD:-}" && exit 0
input="$(cat)"
if command -v jq >/dev/null 2>&1; then
  file="$(printf '%s' "$input" | jq -r '.tool_input.file_path // empty' 2>/dev/null)"
else
  file="$(printf '%s' "$input" | sed -n 's/.*"file_path"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -n1)"
fi
name="${file##*/}"
[[ "$name" == .env.example ]] && exit 0
if [[ "$name" == .env || "$name" == .env.* || "$name" == *.env ]]; then
  echo "destructive-guard: access to .env files is blocked ($file)" >&2
  exit 2
fi
exit 0
