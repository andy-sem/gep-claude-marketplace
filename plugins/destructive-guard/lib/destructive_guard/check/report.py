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
        lines = [what, f"decision: {r['decision']}"]
        if r["reason"]:
            lines.append(f"reason:   {r['reason']}")
        if r.get("risk") is not None:
            lines.append(f"risk:     {cls._js(round(r['risk'], 2))}")
        if r.get("warning"):
            lines.append(f"warning:  {r['warning']}")
        return "\n".join(lines)

    @classmethod
    def format_config(cls, c: Mapping[str, Any]) -> str:
        lines: list[str] = []
        if c.get("error"):
            lines.append(f"ERROR: {c['error']}")
        if "enabled" in c:
            lines += [
                f"enabled:       {cls._js(c['enabled'])}",
                f"env guard:     {cls._js(c['envGuard'])}",
                f"log:           {c['log'] if c['log'] is not None else '(off)'}",
            ]
        j = c["jev"]
        if j.get("error"):
            lines.append(f"jev:           ERROR {j['error']} (api key {j['apiKey']})")
        else:
            lines += [
                f"jev:           {j['url']}, model {j['model']}, api key {j['apiKey']}",
                f"  prompt:      {j['prompt']} (question {j['question']}; ask {','.join(j['ask'])})",
                f"  thresholds:  escalate {cls._js(j['escalateThreshold'])}; timeout {cls._js(j['timeoutMs'])}ms",
            ]
        if c.get("sessionWarning"):
            lines.append(f"session warning: {c['sessionWarning']}")
        return "\n".join(lines)

    @staticmethod
    def _dump(v: Any) -> str:
        return json.dumps(v, indent=2, ensure_ascii=False)
