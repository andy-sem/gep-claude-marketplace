import json
from collections.abc import Mapping
from typing import Any

from .dry_run import GateDryRun


class CheckReport:
    """Renders a dry run's answer and the effective configuration as text or JSON."""

    @staticmethod
    def _js(v: Any) -> str:
        """A value the way a JS template literal prints it."""
        if v is True:
            return "true"
        if v is False:
            return "false"
        if v is None:
            return "null"
        return str(GateDryRun._num(v))

    @staticmethod
    def _compact(v: Any) -> str:
        return json.dumps(v, ensure_ascii=False, separators=(",", ":"))

    @classmethod
    def format_check(cls, r: Mapping[str, Any]) -> str:
        what = f"Bash: {r['command']}" if r["tool"] == "Bash" else f"{r['tool']} {cls._compact(r['input'])}"
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

    @classmethod
    def format_config(cls, c: Mapping[str, Any]) -> str:
        lines: list[str] = []
        if c.get("error"):
            lines.append(f"ERROR: {c['error']} (every gated call asks)")
        if "enabled" in c:
            lines += [
                f"enabled:       {cls._js(c['enabled'])}",
                f"packs:         {', '.join(c['packs']) or '(none)'}",
                f"rules files:   {', '.join(c['rulesFiles']) or '(none)'}",
                f"disabled ids:  {', '.join(c['disableRules']) or '(none)'}",
                f"strict:        {cls._js(c['strict'])}",
                f"env guard:     {cls._js(c['envGuard'])}",
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
                f"  thresholds:  escalate {cls._js(j['escalateThreshold'])}; timeout {cls._js(j['timeoutMs'])}ms",
            ]
        return "\n".join(lines)

    @staticmethod
    def _dump(v: Any) -> str:
        return json.dumps(v, indent=2, ensure_ascii=False)
