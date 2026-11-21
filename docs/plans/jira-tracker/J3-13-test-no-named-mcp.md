# Task 13: `tests/test_no_named_mcp.py` (new)

Package **J3** · prev [Task 12](J3-12-plugin-readme.md) · next [Task 14](J3-14-claude-md.md) · [index](README.md)

## Goal

A guard test: Jira support relies on the session's tools, so the shipped Markdown must never drift into naming a real MCP server or its tools. This repeats, for the workflow plugin, the check that `destructive-guard` already has for `jev/*.json` (`test_jev_prompt.py:80`).

## Test

```python
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
```

Every doc of this plan uses the placeholder site `acme.example.net`, so the `atlassian` check needs no exemption.

## Steps

- [ ] **1.** Write the test. Run it: green after Tasks 01–12.
- [ ] **2.** Check that it would catch a slip: add `mcp__foo__bar` to a copy of `SKILL.md` in `tmp_path`, or simply trust the regex review. No permanent fixture is needed.

## Done when

- `uv run pytest plugins/gated-dev-simple-workflow/tests/test_no_named_mcp.py` is green.
