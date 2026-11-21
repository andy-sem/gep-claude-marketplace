"""Shipped workflow docs name no real MCP server or tool (public repo hygiene)."""

import re
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1]
FILES = sorted(p for p in PLUGIN.rglob("*.md") if "tests" not in p.parts)
# Made-up names used in examples are allowed.
ALLOWED = re.compile(r"mcp__(tracker|db|chat)__\w+")


def test_markdown_files_found():
    assert any(p.name == "SKILL.md" for p in FILES)


def test_no_named_mcp_servers():
    for path in FILES:
        text = ALLOWED.sub("", path.read_text(encoding="utf-8"))
        assert not re.search(r"mcp__\w+", text), path
        assert not re.search(r"atlassian|mcp__plugin_", text, re.IGNORECASE), path
