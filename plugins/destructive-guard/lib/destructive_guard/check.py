"""Dry run for destructive-guard (port of check.mjs): what would the gate do with a call, and what
is the effective configuration? Used by the `check` skill. Builds the config exactly like the hook
(read_config -> build_rules -> gate), never runs the call, and by default never contacts Jev
(`--jev` opts in to a real request).

    check.py [--json] [--jev] [--cwd DIR] -- <command...>       a Bash command
    check.py [--json] [--jev] --mcp <tool> [<json input>]       an MCP call
    check.py [--json] --config                                  effective config

No call given -> --config. Exit code 0 on success (whatever the decision), 2 on usage errors.
"""

import json
import os
import re
import sys
from collections.abc import Mapping
from typing import Any

from .config import build_rules, read_config
from .errors import ConfigError, RulesError, UsageError
from .gate_engine import gate

JEV_VARS = re.compile(r"^(GATE_JEV|TYPESAFE_API_KEY)")


def parse_args(argv: list[str]) -> dict[str, Any]:
    opts: dict[str, Any] = {"json": False, "jev": False, "cwd": None, "mode": "config"}
    args = list(argv)
    while args:
        a = args.pop(0)
        if a == "--json":
            opts["json"] = True
        elif a == "--jev":
            opts["jev"] = True
        elif a == "--config":
            opts["mode"] = "config"
        elif a == "--cwd":
            if not args:
                raise UsageError("--cwd needs a directory")
            opts["cwd"] = args.pop(0)
        elif a == "--mcp":
            tool = args.pop(0) if args else None
            if not tool or not tool.startswith("mcp__"):
                raise UsageError("--mcp needs a tool name starting with mcp__")
            raw = " ".join(args) if args else "{}"
            try:
                tool_input = json.loads(raw, parse_constant=_reject_constant)
            except ValueError:
                raise UsageError(f"MCP input is not valid JSON: {raw}") from None
            if not isinstance(tool_input, dict):
                raise UsageError("MCP input must be a JSON object")
            return {**opts, "mode": "mcp", "tool": tool, "input": tool_input}
        elif a == "--":
            if not args:
                raise UsageError("no command after --")
            return {**opts, "mode": "bash", "command": " ".join(args)}
        elif a.startswith("--"):
            raise UsageError(f"unknown option {a}")
        else:
            return {**opts, "mode": "bash", "command": " ".join([a, *args])}
    return opts


def _reject_constant(name: str) -> Any:
    raise ValueError(f"invalid JSON constant {name}")


def _num(x: Any) -> Any:
    """JS prints 1 for 1.0."""
    return int(x) if isinstance(x, float) and x.is_integer() else x


def _jev_summary(env: Mapping[str, str]) -> dict[str, Any]:
    """Jev settings for display; never includes the API key itself."""
    toggle = env.get("GATE_JEV")
    if not toggle or toggle.strip() in ("", "0"):
        return {"enabled": False}
    try:
        from .gate_jev import read_jev_config

        cfg = read_jev_config(env)
        if not cfg:
            return {"enabled": False}
        rest = {k: v for k, v in cfg.items() if k not in ("apiKey", "prompt")}
        for k in ("allowThreshold", "escalateThreshold"):
            if k in rest:
                rest[k] = _num(rest[k])
        prompt = cfg["prompt"]
        return {
            "enabled": True,
            **rest,
            "apiKey": "[set]" if cfg.get("apiKey") else "[missing]",
            "prompt": (env.get("GATE_JEV_PROMPT") or "").strip() or "destructive",
            "question": prompt["question"],
            "ask": prompt["ask"],
            "safe": prompt["safe"],
        }
    except Exception as e:  # noqa: BLE001
        return {"enabled": True, "error": f"gate-config: {e}"}


def effective_config(env: Mapping[str, str]) -> dict[str, Any]:
    """Effective configuration plus the loaded rule ids, or the config error the hook would answer with."""
    out: dict[str, Any] = {}
    try:
        config = read_config(env)
        out.update(config)
        if config["enabled"]:
            rules = build_rules(config)
            out["ruleIds"] = [r["id"] for r in (rules.get("rules") or []) if r.get("id")]
    except (ConfigError, RulesError) as e:
        out["error"] = f"gate-config: {e}"
    out["jev"] = _jev_summary(env)
    return out


def _answer(result: dict | None) -> dict[str, Any]:
    """{decision, reason, source}: source is the rule id or the gate's own tag (script, unparsable,
    gate-config, jev) taken from the reason prefix."""
    if not result:
        return {"decision": "none", "reason": None, "source": None}
    reason = result["reason"]
    i = reason.find(": ")
    return {"decision": result["decision"], "reason": reason, "source": reason[:i] if i > 0 else reason}


def check_call(
    call: Mapping[str, Any], *, env: Mapping[str, str], cwd: str | None = None, jev: bool = False
) -> dict[str, Any]:
    """The gate's answer for one call. Never executes it."""
    bash = call["mode"] == "bash"
    if bash:
        hook_input: dict[str, Any] = {"tool_name": "Bash", "tool_input": {"command": call["command"]}}
        target: dict[str, Any] = {"tool": "Bash", "command": call["command"]}
    else:
        hook_input = {"tool_name": call["tool"], "tool_input": call["input"]}
        target = {"tool": call["tool"], "input": call["input"]}
    if cwd:
        hook_input["cwd"] = cwd
    gate_env = env if jev else {k: v for k, v in env.items() if not JEV_VARS.match(k)}

    try:
        config = read_config(env, cwd=cwd or os.getcwd())
    except ConfigError as e:
        return {**target, **_answer({"decision": "ask", "reason": f"gate-config: {e}"}), "rule": None}
    if not config["enabled"]:
        return {**target, "decision": "none", "reason": "gate disabled (GATE_ENABLED=0)", "source": None, "rule": None}
    try:
        rules = build_rules(config)
    except (ConfigError, RulesError) as e:
        return {**target, **_answer({"decision": "ask", "reason": f"gate-config: {e}"}), "rule": None}
    trace: dict = {}
    result = gate(hook_input, rules, env=gate_env, cwd=cwd, strict=config["strict"], trace=trace)
    jev_info = _jev_summary(env)
    in_scope = (
        ("bash" if bash else "mcp") in jev_info["scope"] if jev_info["enabled"] and not jev_info.get("error") else False
    )
    return {
        **target,
        **_answer(result),
        "rule": _answer(trace["rule"]) if trace.get("rule") else None,
        "jev": "consulted" if jev else "would be consulted (pass --jev)" if in_scope else "off",
    }


def _js(v: Any) -> str:
    """A value the way a JS template literal prints it."""
    if v is True:
        return "true"
    if v is False:
        return "false"
    if v is None:
        return "null"
    return str(_num(v))


def _compact(v: Any) -> str:
    return json.dumps(v, ensure_ascii=False, separators=(",", ":"))


def format_check(r: Mapping[str, Any]) -> str:
    what = f"Bash: {r['command']}" if r["tool"] == "Bash" else f"{r['tool']} {_compact(r['input'])}"
    lines = [what]
    if r["decision"] == "ask":
        lines += ["decision: ask", f"source:   {r['source']}", f"reason:   {r['reason']}"]
    else:
        lines.append("decision: none (the gate has no opinion; Claude Code's own permission rules decide)")
    if r["reason"] and r["decision"] != "ask":
        lines.append(f"reason:   {r['reason']}")
    rule = r.get("rule")
    if rule and rule["reason"] != r["reason"]:
        lines.append(f"rules alone: {rule['decision']} ({rule['reason']})")
    if r.get("jev"):
        lines.append(f"jev:      {r['jev']}")
    return "\n".join(lines)


def format_config(c: Mapping[str, Any]) -> str:
    lines: list[str] = []
    if c.get("error"):
        lines.append(f"ERROR: {c['error']} (every gated call asks)")
    if "enabled" in c:
        lines += [
            f"enabled:       {_js(c['enabled'])}",
            f"packs:         {', '.join(c['packs']) or '(none)'}",
            f"rules files:   {', '.join(c['rulesFiles']) or '(none)'}",
            f"disabled ids:  {', '.join(c['disableRules']) or '(none)'}",
            f"strict:        {_js(c['strict'])}",
            f"env guard:     {_js(c['envGuard'])}",
            f"log:           {c['log'] if c['log'] is not None else '(off)'}",
        ]
        if "ruleIds" in c:
            lines.append(f"rules ({len(c['ruleIds'])}): {', '.join(c['ruleIds'])}")
    j = c["jev"]
    if not j["enabled"]:
        lines.append("jev:           off")
    elif j.get("error"):
        lines.append(f"jev:           ERROR {j['error']}")
    else:
        lines += [
            f"jev:           on ({j['url']}, model {j['model']}, api key {j['apiKey']})",
            f"  prompt:      {j['prompt']} (question {j['question']}; ask {','.join(j['ask'])}; safe {','.join(j['safe'])})",
            f"  scope:       {','.join(j['scope'])}   can lift: {_js(j['canLift'])}",
            f"  thresholds:  allow {_js(j['allowThreshold'])}, escalate {_js(j['escalateThreshold'])}; timeout {_js(j['timeoutMs'])}ms",
        ]
    return "\n".join(lines)


def _dump(v: Any) -> str:
    return json.dumps(v, indent=2, ensure_ascii=False)


def render(argv: list[str], *, env: Mapping[str, str], cwd: str) -> tuple[int, str]:
    """(exit code, output text without the trailing newline)."""
    try:
        opts = parse_args(argv)
    except UsageError as e:
        return 2, f"usage error: {e}"
    if opts["mode"] == "config":
        c = effective_config(env)
        return 0, _dump(c) if opts["json"] else format_config(c)
    r = check_call(opts, env=env, cwd=opts["cwd"] or cwd, jev=opts["jev"])
    return 0, _dump(r) if opts["json"] else format_check(r)


def run(argv: list[str], *, env: Mapping[str, str], cwd: str) -> int:
    code, out = render(argv, env=env, cwd=cwd)
    sys.stdout.buffer.write((out + "\n").encode("utf-8", errors="replace"))
    sys.stdout.buffer.flush()
    return code


def main() -> int:
    return run(sys.argv[1:], env=os.environ, cwd=os.getcwd())
