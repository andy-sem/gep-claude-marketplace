"""Optional Jev (TypeSafe) layer for the approval gate (port of gate-jev.mjs).

Imported by the gate only when GATE_JEV is set. For every Bash command and every MCP call it asks
Jev the configured question (default: could the call delete, overwrite or irreversibly change data,
locally or remotely; see jev/*.json and GATE_JEV_PROMPT; GATE_JEV_SCOPE limits it to Bash or MCP
calls). Jev can add an `ask` or, unless GATE_JEV_CAN_LIFT=0, lift a rule `ask` (no output, so Claude
Code's own permission rules decide); it never emits an `allow`. Any request failure leaves the rule
result unchanged.

Data keeps the JS shape (dicts with `apiKey`, `timeoutMs`, `latencyMs`, ...). The request takes an
injectable `opener` (the twin of JS `fetchImpl`), `sleep` and `clock`, so unit tests need no network.
"""

import json
import math
import os
import random
import re
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .errors import JevConfigError
from .paths import project_path

JEV_URL = "https://api.typesafe.ai/v1/systemone"

DEFAULTS = {
    "allowThreshold": 0.95,
    "escalateThreshold": 0.5,
    "model": "jev-latest",
    "timeoutMs": 1500,
}
MAX_TIMEOUT_MS = 30000
MAX_COMMAND_CHARS = 8000
MAX_INPUT_CHARS = 8000
MAX_SCRIPTS_BYTES = 65536
PROMPTS_DIR = Path(__file__).resolve().parent.parent.parent / "jev"
DEFAULT_PROMPT = "destructive"
LOOPBACK = {"localhost", "127.0.0.1", "::1"}
SCOPES = ["bash", "mcp"]


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def _optional(env: Mapping[str, str], name: str) -> str | None:
    """Empty optional variables count as unset."""
    v = env.get(name)
    if v is None or v.strip() == "":
        return None
    return v.strip()


def _scope(env: Mapping[str, str]) -> list[str]:
    """GATE_JEV_SCOPE: comma list of call kinds sent to Jev (default: all)."""
    raw = _optional(env, "GATE_JEV_SCOPE")
    if raw is None:
        return list(SCOPES)
    items = [s.strip().lower() for s in raw.split(",")]
    if any(s not in SCOPES for s in items):
        raise JevConfigError(f"GATE_JEV_SCOPE must be a comma list of {', '.join(SCOPES)}")
    return [s for s in SCOPES if s in items]


def _can_lift(env: Mapping[str, str]) -> bool:
    """GATE_JEV_CAN_LIFT: 1 (default) lets a confident safe answer lift a rule ask; 0 only adds asks."""
    raw = _optional(env, "GATE_JEV_CAN_LIFT")
    if raw is None or raw == "1":
        return True
    if raw == "0":
        return False
    raise JevConfigError("GATE_JEV_CAN_LIFT must be 0 or 1")


_PROBABILITY = re.compile(r"0(\.[0-9]+)?|1(\.0+)?|\.[0-9]+")


def _probability(env: Mapping[str, str], name: str, fallback: float) -> float:
    raw = _optional(env, name)
    if raw is None:
        return fallback
    if not _PROBABILITY.fullmatch(raw):
        raise JevConfigError(f"{name} must be a number from 0 to 1")
    n = float(raw)
    if not 0 <= n <= 1:
        raise JevConfigError(f"{name} must be a number from 0 to 1")
    return n


def _check_url(url: str) -> None:
    try:
        parts = urlsplit(url)
        parts.port  # noqa: B018 - raises ValueError for a bad port
        host = parts.hostname
    except ValueError:
        raise JevConfigError("GATE_JEV_URL is not a valid URL") from None
    scheme = parts.scheme.lower()
    if not scheme or (scheme in ("http", "https") and not host):
        raise JevConfigError("GATE_JEV_URL is not a valid URL")
    # The API key must not travel in clear text, except to a local test server.
    if scheme != "https" and not (scheme == "http" and host in LOOPBACK):
        raise JevConfigError("GATE_JEV_URL must use https")


def read_jev_config(env: Mapping[str, str], *, cwd: str | Path | None = None) -> dict | None:
    """None when Jev is off. Raises JevConfigError when Jev is on and a variable is missing or invalid."""
    cwd = cwd if cwd is not None else os.getcwd()
    toggle = _optional(env, "GATE_JEV")
    if toggle is None or toggle == "0":
        return None
    if toggle != "1":
        raise JevConfigError("GATE_JEV must be 1 or unset")

    api_key = _optional(env, "TYPESAFE_API_KEY")
    if not api_key:
        raise JevConfigError("GATE_JEV=1 but TYPESAFE_API_KEY is not set")

    raw_timeout = _optional(env, "GATE_JEV_TIMEOUT_MS")
    timeout_ms = DEFAULTS["timeoutMs"]
    if raw_timeout is not None:
        if not re.fullmatch(r"[0-9]+", raw_timeout):
            raise JevConfigError(f"GATE_JEV_TIMEOUT_MS must be an integer from 1 to {MAX_TIMEOUT_MS}")
        timeout_ms = int(raw_timeout)
    if timeout_ms < 1 or timeout_ms > MAX_TIMEOUT_MS:
        raise JevConfigError(f"GATE_JEV_TIMEOUT_MS must be an integer from 1 to {MAX_TIMEOUT_MS}")

    url = _optional(env, "GATE_JEV_URL") or JEV_URL
    _check_url(url)

    log = _optional(env, "GATE_JEV_LOG")
    return {
        "apiKey": api_key,
        "url": url,
        "model": _optional(env, "GATE_JEV_MODEL") or DEFAULTS["model"],
        "allowThreshold": _probability(env, "GATE_JEV_ALLOW_THRESHOLD", DEFAULTS["allowThreshold"]),
        "escalateThreshold": _probability(env, "GATE_JEV_ESCALATE_THRESHOLD", DEFAULTS["escalateThreshold"]),
        "timeoutMs": timeout_ms,
        "logPath": None if log is None else project_path(log, env, cwd),
        "scope": _scope(env),
        "canLift": _can_lift(env),
        "prompt": prompt_from_env(env, cwd=cwd),
    }


# ---------------------------------------------------------------------------
# Prompt (the question Jev answers)
# ---------------------------------------------------------------------------


def validate_prompt(p: Any, where: str = "prompt") -> dict:
    """A prompt is {question, instructions, context, criteria, ask, safe}: `criteria` maps each choice
    to {description, examples}, `ask` lists the choices whose probabilities add up to the risk, `safe`
    the choices that may lift a rule ask. Raises JevConfigError when the shape is wrong."""

    def bad(msg: str) -> None:
        raise JevConfigError(f"{where}: {msg}")

    if not isinstance(p, dict):
        bad("must be a JSON object")
    q = p.get("question")
    if not isinstance(q, str) or not re.fullmatch(r"[a-z][a-z0-9_]*", q):
        bad("question must be a snake_case id")
    ins = p.get("instructions")
    if not isinstance(ins, str) or not ins.strip():
        bad("instructions must be a non-empty string")
    ctx = p.get("context")
    if not isinstance(ctx, dict) or any(not isinstance(v, str) for v in ctx.values()):
        bad("context must be an object of strings")
    criteria = p.get("criteria")
    if not isinstance(criteria, dict):
        bad("criteria must be an object")
    choices = list(criteria)
    if len(choices) < 2:
        bad("criteria needs at least two choices")
    for c, o in criteria.items():
        if (
            not isinstance(o, dict)
            or not isinstance(o.get("description"), str)
            or not isinstance(o.get("examples"), list)
            or any(not isinstance(e, str) for e in o["examples"])
        ):
            bad(f"criteria.{c} needs a description and string examples")
    for key in ("ask", "safe"):
        items = p.get(key)
        if not isinstance(items, list) or not items or any(c not in choices for c in items):
            bad(f"{key} must be a non-empty list of criteria choices")
    if any(c in p["safe"] for c in p["ask"]):
        bad("ask and safe must not overlap")
    return p


def _read_prompt_file(path: str | Path, where: str) -> dict:
    try:
        parsed = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise JevConfigError(f"{where}: cannot read {path}: {e}") from None
    return validate_prompt(parsed, where)


def builtin_prompt(name: str) -> dict:
    """A built-in prompt by name (jev/<name>.json)."""
    if not re.fullmatch(r"[a-z0-9-]+", name):
        raise JevConfigError(f'unknown built-in Jev prompt "{name}"')
    return _read_prompt_file(PROMPTS_DIR / f"{name}.json", f"prompt {name}")


def prompt_from_env(env: Mapping[str, str], *, cwd: str | Path | None = None) -> dict:
    """GATE_JEV_PROMPT: a built-in name (default "destructive") or a path to a prompt JSON file
    (relative paths resolve against the project). GATE_JEV_INSTRUCTIONS, GATE_JEV_CONTEXT and
    GATE_JEV_POLICY then replace the question text, context.project and context.policy."""
    cwd = cwd if cwd is not None else os.getcwd()
    ref = _optional(env, "GATE_JEV_PROMPT") or DEFAULT_PROMPT
    if "/" in ref or ref.endswith(".json"):
        base = _read_prompt_file(project_path(ref, env, cwd), "GATE_JEV_PROMPT")
    else:
        base = builtin_prompt(ref)
    prompt = {**base, "context": dict(base["context"])}
    instructions = _optional(env, "GATE_JEV_INSTRUCTIONS")
    if instructions:
        prompt["instructions"] = instructions
    project = _optional(env, "GATE_JEV_CONTEXT")
    if project:
        prompt["context"]["project"] = project
    policy = _optional(env, "GATE_JEV_POLICY")
    if policy:
        prompt["context"]["policy"] = policy
    return prompt


# ---------------------------------------------------------------------------
# Redaction
# ---------------------------------------------------------------------------

R = "[REDACTED]"
ENV_LINE_REMOVED = "[line removed: .env reference]"
# JS `\s`: ASCII whitespace plus the Unicode spaces (Python's `\s` with re.ASCII is ASCII only).
_WS = "\t\n\v\f\r    -     　﻿"
_SECRET_NAME = (
    r"[\w-]*(?:token|passw(?:or)?d|pwd|secret|api[_-]?key|apikey|auth\w*|credential|private[_-]?key)[\w-]*"
)
_FLAGS = re.ASCII | re.IGNORECASE
_SECRET_KEY_RE = re.compile(f"{_SECRET_NAME}", _FLAGS)
_SQL_KEYS = {"query", "sql", "statement"}

_URL_CREDENTIALS = re.compile(rf"\b([a-z][a-z0-9+.-]*://)[^{_WS}/@'\"]+@", _FLAGS)
_AUTH_SCHEME = re.compile(rf"\b(Bearer|Basic|Token)[{_WS}]+[^{_WS}'\"]+", _FLAGS)
# The lookbehind starts a match only at the beginning of a name run. The same matches as JS (a name
# is the whole [\w-] run around the keyword), but a long keyword-free run is scanned once, not once
# per start position (quadratic backtracking).
_SECRET_ASSIGN = re.compile(
    rf"(?<![\w-])({_SECRET_NAME})([{_WS}]*[=:][{_WS}]*)(\"[^\"]*\"|'[^']*'|[^{_WS}'\"]+)", _FLAGS
)
_SECRET_FLAG = re.compile(
    rf"([{_WS}]--?{_SECRET_NAME})([{_WS}]+)(\"[^\"]*\"|'[^']*'|[^{_WS}'\"-][^{_WS}'\"]*)", _FLAGS
)
_ENV_ASSIGN = re.compile(
    rf"(^|[{_WS};&|(])([A-Za-z_][A-Za-z0-9_]*)=(\"[^\"]*\"|'[^']*'|[^{_WS};&|)]*)", re.ASCII
)
_HEX_RUN = re.compile(r"\b[0-9a-f]{32,}\b", _FLAGS)
_LONG_RUN = re.compile(r"[A-Za-z0-9+/_-]{32,}={0,2}", re.ASCII)
_ENV_FILE = re.compile(r"(^|[^A-Za-z0-9])\.env", re.ASCII)
_DOLLAR_QUOTED = re.compile(r"(\$[A-Za-z_]\w*\$|\$\$)[\s\S]*?\1", re.ASCII)
_SQL_STRING = re.compile(r"'(?:[^']|'')*'")


def references_env_file(command: str) -> bool:
    """Commands that mention .env files (`.env`, `apps/x/.env.local`, `.envrc`) are never sent."""
    return _ENV_FILE.search(command) is not None


def _looks_encoded(run: str) -> bool:
    return bool(re.search("[0-9]", run) and re.search("[A-Z]", run) and re.search("[a-z]", run))


def _redact_text(text: str, *, env_assignments: bool = True) -> str:
    """The redaction rules shared by commands, scripts and MCP inputs. `env_assignments` is off for
    SQL, where `id=5` is not a shell assignment."""
    # https://user:pass@host -> https://[REDACTED]@host
    out = _URL_CREDENTIALS.sub(lambda m: f"{m[1]}{R}@", text)
    out = _AUTH_SCHEME.sub(lambda m: f"{m[1]} {R}", out)
    # NAME=value / NAME: value where NAME looks like a secret
    out = _SECRET_ASSIGN.sub(lambda m: f"{m[1]}{m[2]}{R}", out)
    # --password value / -token value
    out = _SECRET_FLAG.sub(lambda m: f"{m[1]}{m[2]}{R}", out)
    if env_assignments:
        # Environment assignments: FOO=bar cmd, export FOO=bar, env FOO=bar cmd
        out = _ENV_ASSIGN.sub(lambda m: f"{m[1]}{m[2]}={R}", out)
    out = _HEX_RUN.sub(R, out)
    return _LONG_RUN.sub(lambda m: R if _looks_encoded(m[0]) else m[0], out)


def redact(command: str) -> str | None:
    """The command with secrets replaced, or None when it must not be sent."""
    if references_env_file(command):
        return None
    return _redact_text(command)


def _drop_env_lines(text: str) -> str:
    """Lines that reference an .env file are removed instead of skipping the call."""
    return "\n".join(ENV_LINE_REMOVED if references_env_file(line) else line for line in text.split("\n"))


def redact_script(text: str) -> str:
    """Script and file contents: `.env` lines removed, then the shared rules. The call is never skipped."""
    return _redact_text(_drop_env_lines(text))


def _redact_sql_literals(sql: str) -> str:
    """Single-quoted literals (with '' escapes) and dollar-quoted bodies hold data, not structure:
    Jev needs the statement kind, not the values."""
    out = _DOLLAR_QUOTED.sub(lambda m: f"{m[1]}{R}{m[1]}", sql)
    return _SQL_STRING.sub(f"'{R}'", out)


def _redact_mcp_value(value: Any, key: str) -> Any:
    if isinstance(value, str):
        text = _drop_env_lines(value)
        if key in _SQL_KEYS:
            return _redact_text(_redact_sql_literals(text), env_assignments=False)
        return _redact_text(text)
    if isinstance(value, list):
        return [_redact_mcp_value(v, key) for v in value]
    if isinstance(value, dict):
        return {k: R if _SECRET_KEY_RE.fullmatch(k) else _redact_mcp_value(v, k) for k, v in value.items()}
    return value


def redact_mcp_input(tool_input: Any) -> str:
    """An MCP tool input as redacted JSON text."""
    redacted = _redact_mcp_value({} if tool_input is None else tool_input, "")
    return _dumps(redacted)


def _dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


# ---------------------------------------------------------------------------
# State and answer
# ---------------------------------------------------------------------------

_default_prompt: dict | None = None


def _prompt_of(cfg: Mapping[str, Any]) -> dict:
    global _default_prompt
    if cfg.get("prompt"):
        return cfg["prompt"]
    if _default_prompt is None:
        _default_prompt = builtin_prompt(DEFAULT_PROMPT)
    return _default_prompt


def request_body(state: dict, model: str, prompt: dict) -> dict:
    return {
        "model": model,
        "state": {**state, "context": prompt["context"]},
        "questions": {
            prompt["question"]: {
                "type": "choice",
                "instructions": prompt["instructions"],
                "criteria": prompt["criteria"],
            }
        },
    }


def _byte_length(text: str) -> int:
    return len(text.encode("utf-8", "replace"))


def scripts_payload(files: list[dict]) -> tuple[list[dict], list[str]]:
    """Scripts go to Jev in collection order, redacted, up to 64 KB in total: the file that crosses
    the cap is cut, the rest are left out. The notes say what was cut."""
    scripts: list[dict] = []
    notes: list[str] = []
    used = 0
    cut_path: str | None = None
    omitted: list[str] = []
    for file in files:
        content = redact_script(file["content"])
        size = _byte_length(content)
        if file.get("truncated"):
            notes.append(f"{file['path']} cut at 64 KB")
        if cut_path or omitted:
            omitted.append(file["path"])
        elif used + size <= MAX_SCRIPTS_BYTES:
            scripts.append({"path": file["path"], "content": content})
            used += size
        elif used < MAX_SCRIPTS_BYTES:
            room = MAX_SCRIPTS_BYTES - used
            cut = content.encode("utf-8", "replace")[:room].decode("utf-8", "replace")
            scripts.append({"path": file["path"], "content": cut})
            used = MAX_SCRIPTS_BYTES
            cut_path = file["path"]
        else:
            omitted.append(file["path"])
    if cut_path or omitted:
        parts = []
        if cut_path:
            parts.append(f"{cut_path} truncated")
        if omitted:
            parts.append(f"omitted: {', '.join(omitted)}")
        notes.append(f"scripts cut at 64 KB total: {'; '.join(parts)}")
    return scripts, notes


def problem_notes(problems: list[dict]) -> list[str]:
    """One note per file the gate could not read safely, so that Jev does not take an empty `scripts`
    list for "nothing to read". Exempt files are left out, and so are files cut at 64 KB (the cut is
    noted already). The text is redacted like a script."""
    return [
        f"{redact_script(p['path'])} not read: {p['reason']}"
        for p in problems
        if not p.get("exempt") and p.get("reason") != "exceeds 64 KB"
    ]


def build_state(call: Mapping[str, Any]) -> dict | None:
    """The request state for a call, or None when the call must not be sent (a Bash command that
    references an .env file). `call` is {tool: "Bash", command, scripts, problems} or {tool, input}."""
    if call["tool"] == "Bash":
        redacted = redact(call["command"])
        if redacted is None:
            return None
        notes = []
        if len(redacted) > MAX_COMMAND_CHARS:
            notes.append(f"command cut to {MAX_COMMAND_CHARS} of {len(redacted)} characters")
        scripts, script_notes = scripts_payload(call.get("scripts") or [])
        return {
            "tool": "Bash",
            "command": redacted[:MAX_COMMAND_CHARS],
            "scripts": scripts,
            "notes": [*notes, *script_notes, *problem_notes(call.get("problems") or [])],
        }
    text = redact_mcp_input(call.get("input"))
    notes = []
    if len(text) > MAX_INPUT_CHARS:
        notes.append(f"input cut to {MAX_INPUT_CHARS} of {len(text)} characters")
    return {"tool": call["tool"], "input": text[:MAX_INPUT_CHARS], "notes": notes}


def _get(obj: Any, key: str) -> Any:
    return obj.get(key) if isinstance(obj, dict) else None


def parse_answer(body: Any, prompt: dict | None = None) -> dict | None:
    """The probabilities map, or None when the response is malformed."""
    prompt = prompt or _prompt_of({})
    choices = list(prompt["criteria"])
    answer = _get(_get(body, "answers"), prompt["question"])
    probs = _get(answer, "probabilities")
    if _get(answer, "type") != "choice" or not isinstance(probs, dict):
        return None
    total = 0.0
    for choice in choices:
        p = probs.get(choice)
        if isinstance(p, bool) or not isinstance(p, (int, float)) or not 0 <= p <= 1:
            return None
        total += p
    if abs(total - 1) > 0.05:
        return None
    return {c: probs[c] for c in choices}


# ---------------------------------------------------------------------------
# Jev request
# ---------------------------------------------------------------------------


def retry_delay(attempt: int, retry_after: str | None, *, now: Callable[[], datetime] = lambda: datetime.now(UTC)) -> float:
    """Milliseconds to wait before the next attempt: `retry-after` (seconds or HTTP-date), else backoff."""
    if retry_after:
        try:
            seconds = float(retry_after)
        except ValueError:
            seconds = None
            try:
                when = parsedate_to_datetime(retry_after)
                if when.tzinfo is None:
                    when = when.replace(tzinfo=UTC)
                seconds = max(0.0, (when - now()).total_seconds())
            except (TypeError, ValueError, IndexError):
                pass
        if seconds is not None and math.isfinite(seconds) and seconds >= 0:
            return seconds * 1000
    return 100 * 2 ** (attempt - 1) + random.randrange(50)


def _is_timeout(e: BaseException) -> bool:
    reason = getattr(e, "reason", None)
    return isinstance(e, TimeoutError) or isinstance(reason, TimeoutError)


def ask_jev(
    state: dict,
    cfg: Mapping[str, Any],
    *,
    opener: Callable[..., Any] = urllib.request.urlopen,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> dict:
    """Calls Jev within one overall time budget (retries included). Never raises. Returns
    {probabilities, usage, latencyMs} or {error, latencyMs}; latencyMs covers all attempts and `usage`
    is the token usage Jev reports, or None."""
    started = clock()
    deadline = started + cfg["timeoutMs"] / 1000

    def elapsed() -> int:
        return round((clock() - started) * 1000)

    def fail(error: str) -> dict:
        return {"error": error, "latencyMs": elapsed()}

    try:
        prompt = _prompt_of(cfg)
        body = _dumps(request_body(state, cfg["model"], prompt)).encode("utf-8", "replace")
        attempt = 0
        while True:
            attempt += 1
            remaining = deadline - clock()
            if remaining <= 0:
                return fail("timeout")
            request = urllib.request.Request(
                cfg["url"],
                data=body,
                method="POST",
                headers={"authorization": f"Bearer {cfg['apiKey']}", "content-type": "application/json"},
            )
            status = 0
            headers: Any = None
            raw = b""
            try:
                res = opener(request, timeout=remaining)
                try:
                    status = res.status
                    headers = res.headers
                    if 200 <= status < 300:
                        raw = res.read()
                finally:
                    close = getattr(res, "close", None)
                    if close:
                        close()
            except urllib.error.HTTPError as e:
                status, headers = e.code, e.headers
                e.close()
            except Exception as e:  # noqa: BLE001 - ask_jev never raises
                if _is_timeout(e) or clock() >= deadline:
                    return fail("timeout")
                # An unreadable or cut-off body of an answered request is not a network failure.
                return fail("malformed" if status else "network")
            if status in (429, 529):
                header = headers.get("retry-after") if headers is not None else None
                delay = retry_delay(attempt, header)
                if clock() + delay / 1000 >= deadline:
                    return fail(f"http {status}")
                sleep(delay / 1000)
                continue
            if not 200 <= status < 300:
                return fail(f"http {status}")
            try:
                parsed = json.loads(raw)
            except ValueError:
                return fail("timeout" if clock() >= deadline else "malformed")
            probabilities = parse_answer(parsed, prompt)
            if not probabilities:
                return fail("malformed")
            return {
                "probabilities": probabilities,
                "usage": _get(parsed, "usage"),
                "latencyMs": elapsed(),
            }
    except Exception:  # noqa: BLE001
        return fail("network")


# ---------------------------------------------------------------------------
# Decision
# ---------------------------------------------------------------------------


def _fmt(p: float) -> str:
    """JS `toFixed(2)`: ties round up."""
    return str(Decimal(p).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _top_of(probs: Mapping[str, float], choices: list[str]) -> str:
    """Ties go to the choice listed last (the stronger one in the built-in prompts)."""
    best = choices[0]
    for c in choices[1:]:
        if probs[c] >= probs[best]:
            best = c
    return best


def jev_decision(probs: Mapping[str, float], cfg: Mapping[str, Any]) -> dict | None:
    """"ask" (risk above the escalate threshold), "pass" (lift any rule ask, safe at or above the
    allow threshold) or None (no Jev decision). Jev never emits `allow`."""
    prompt = _prompt_of(cfg)
    ask_choices, safe_choices = prompt["ask"], prompt["safe"]

    def total(choices: list[str]) -> float:
        n = 0.0
        for c in choices:
            n += probs[c]
        return n

    risk = total(ask_choices)
    if risk > cfg["escalateThreshold"]:
        top = _top_of(probs, ask_choices)
        return {"decision": "ask", "reason": f"jev: {top} p={_fmt(probs[top])} risk={_fmt(risk)}"}
    safe = total(safe_choices)
    if safe >= cfg["allowThreshold"]:
        top = _top_of(probs, list(reversed(safe_choices)))
        return {"decision": "pass", "reason": f"jev: {top} p={_fmt(probs[top])} safe={_fmt(safe)}"}
    return None


def audit(cfg: Mapping[str, Any], record: dict) -> None:
    path = cfg.get("logPath")
    if not path:
        return
    try:
        ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        with open(path, "a", encoding="utf-8") as f:
            f.write(_dumps({"ts": ts, **record}) + "\n")
    except Exception:  # noqa: BLE001, S110 - the audit log is best-effort
        pass


def run_jev(
    call: Mapping[str, Any],
    rule_result: dict | None,
    cfg: Mapping[str, Any],
    *,
    opener: Callable[..., Any] = urllib.request.urlopen,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> dict | None:
    """Applies Jev to a Bash command or an MCP call on top of the rule result and returns the final
    gate result: an ask, or None for no output."""
    rule = rule_result.get("reason") if rule_result else None
    state = build_state(call)
    tool = call["tool"]
    if state is None:
        audit(cfg, {"tool": tool, "command": None, "rule": rule, "outcome": "skipped: .env reference", "latencyMs": 0})
        return rule_result
    if tool == "Bash":
        sent: dict = {"command": state["command"], "scripts": [s["path"] for s in state["scripts"]]}
    else:
        sent = {"input": state["input"]}
    result = ask_jev(state, cfg, opener=opener, sleep=sleep, clock=clock)
    probabilities = result.get("probabilities")
    if not probabilities:
        audit(cfg, {"tool": tool, **sent, "rule": rule, "outcome": f"fallback: {result.get('error')}", "latencyMs": result["latencyMs"]})
        return rule_result
    jev = jev_decision(probabilities, cfg)
    # canLift False (GATE_JEV_CAN_LIFT=0): a safe answer leaves the rule result in place, so Jev can
    # only add asks. Missing means the default (True).
    if jev and jev["decision"] == "ask":
        final: dict | None = {"decision": "ask", "reason": jev["reason"]}
    elif jev and jev["decision"] == "pass" and cfg.get("canLift") is not False:
        final = None
    else:
        final = rule_result
    audit(
        cfg,
        {
            "tool": tool,
            **sent,
            "probabilities": probabilities,
            "rule": rule,
            "jev": jev["reason"] if jev else None,
            "decision": final["decision"] if final else "pass",
            "usage": result.get("usage"),
            "latencyMs": result["latencyMs"],
        },
    )
    return final
