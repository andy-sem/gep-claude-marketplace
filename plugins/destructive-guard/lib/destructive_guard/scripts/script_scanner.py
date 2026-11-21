"""Scanning the collected script files for gated programs and patterns."""

import re

from ..rules.rule_loader import Rules
from ..verdict import Verdict


class ScriptScanner:
    """Looks through collected scripts for what the rules gate."""

    def __init__(self, rules: Rules):
        self.rules = rules

    @staticmethod
    def escape_re(s: str) -> str:
        return re.escape(s)

    def program_names(self) -> list[str]:
        """The program names a script could run: those named by the CLI rules and by an mcp-as-cli rule
        (the rules file is the only place that names tools)."""
        names: dict[str, None] = {}
        for rule in self.rules["rules"]:
            kind = rule["kind"]
            if kind in ("cli-allowlist", "cli-gated"):
                if rule.get("scriptScan") is False:
                    continue
                for p in rule["programs"]:
                    names[p] = None
            elif kind == "mcp-as-cli":
                names[rule["program"]] = None
        return list(names)

    def scan_scripts(self, collected: dict | None) -> dict | None:
        """Looks at the non-exempt files and problems: an unreadable, outside-project or oversized file
        asks, then a program name, then a `scriptPatterns` match. Returns an `ask` result or None."""
        if not collected:
            return None
        patterns = self.rules.get("scriptPatterns") or []
        programs = self.program_names()
        # Nothing to look for: no program names and no patterns.
        if not programs and not patterns:
            return None
        problem = next((p for p in collected["problems"] if not p["exempt"]), None)
        if problem:
            return Verdict.ask("script", f"{problem['path']} {problem['reason']}")
        scanned = [f for f in collected["files"] if not f["exempt"]]
        names = [(name, re.compile(rf"(?<![\w.@-]){ScriptScanner.escape_re(name)}(?![\w-])", re.ASCII)) for name in programs]
        for f in scanned:
            for name, rx in names:
                if rx.search(f["content"]):
                    return Verdict.ask("script", f"{f['path']} runs {name}")
        for f in scanned:
            for rx in patterns:
                if rx.search(f["content"]):
                    return Verdict.ask("script", f"{f['path']} references {rx.pattern}")
        return None
