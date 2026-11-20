#!/usr/bin/env bash
# Notification hook: a desktop notification when a /ticket session started by
# the launcher (TICKET_FLOW_KEY set) needs you: a permission prompt, a stop
# point, or an idle wait. macOS: osascript; Linux: notify-send when installed;
# silent elsewhere. GATED_DEV_NOTIFY=0 turns it off. Never fails, never blocks.
#
#   notify.sh                    hook mode: event JSON on stdin
#   notify.sh <title> <message>  direct mode (the /ticket skill, e.g. after a
#                                merge); needs no TICKET_FLOW_KEY
[ "${GATED_DEV_NOTIFY:-1}" = "0" ] && exit 0

if [ "$#" -ge 2 ]; then
  TITLE="$1"
  MSG="$2"
else
  KEY="${TICKET_FLOW_KEY:-}"
  [ -z "$KEY" ] && exit 0
  INPUT="$(cat 2>/dev/null)"
  MSG=""
  if command -v jq >/dev/null 2>&1; then
    MSG="$(printf '%s' "$INPUT" | jq -r '.message // .title // empty' 2>/dev/null)"
  fi
  [ -z "$MSG" ] && MSG="Claude needs your attention"
  TITLE="$KEY needs you"
fi

case "$(uname -s 2>/dev/null)" in
  Darwin)
    command -v osascript >/dev/null 2>&1 && osascript \
      -e 'on run argv' \
      -e 'display notification (item 2 of argv) with title (item 1 of argv) sound name "Glass"' \
      -e 'end run' \
      -- "$TITLE" "$MSG" >/dev/null 2>&1
    ;;
  Linux)
    command -v notify-send >/dev/null 2>&1 && notify-send -- "$TITLE" "$MSG" >/dev/null 2>&1
    ;;
esac
exit 0
