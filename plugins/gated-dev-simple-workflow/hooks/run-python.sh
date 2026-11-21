#!/usr/bin/env bash
# Launcher for this plugin's Python entry points: run-python.sh <script> [args...].
# Interpreter: GATE_INFRA_PYTHON if set, else python3.14, else python3; always
# -I (isolated: ignores PYTHONPATH, user site and the current directory).
# Best-effort, for hooks that must never block the session: no interpreter, a
# too-old one (the entry stub exits 3) or any failure ends silently with exit 0.
py="${GATE_INFRA_PYTHON:-}"
[ -n "$py" ] || py="$(command -v python3.14 || command -v python3)"
[ -n "$py" ] || exit 0
"$py" -I "$@" >/dev/null 2>&1
exit 0
