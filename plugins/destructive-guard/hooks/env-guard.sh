#!/usr/bin/env bash
# PreToolUse guard for Read/Edit/Write: blocks .env* files (exit 2), except
# .env.example. Ported from the inline hook in the source project; Read is
# covered here because a plugin cannot ship permissions.deny entries.
input="$(cat)"
if command -v jq >/dev/null 2>&1; then
  file="$(printf '%s' "$input" | jq -r '.tool_input.file_path // empty' 2>/dev/null)"
else
  file="$(printf '%s' "$input" | sed -n 's/.*"file_path"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -n1)"
fi
[[ "$file" == *.env.example ]] && exit 0
if [[ "$file" == *.env* ]]; then
  echo "destructive-guard: access to .env files is blocked ($file)" >&2
  exit 2
fi
exit 0
