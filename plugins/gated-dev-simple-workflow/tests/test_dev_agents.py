"""The three dev tier agents share one body and differ only where intended."""

import re

import pytest

from gd_testkit import GD

AGENTS = GD / "agents"
TIERS = {
    "godzilla": ("opus", "high"),
    "workhorse": ("sonnet", "high"),
    "pawn": ("haiku", "medium"),
}


def _split(name: str) -> tuple[dict[str, str], str]:
    text = (AGENTS / f"{name}.md").read_text(encoding="utf-8")
    match = re.match(r"---\n(.*?)\n---\n(.*)", text, re.DOTALL)
    assert match, name
    meta = dict(line.split(": ", 1) for line in match.group(1).splitlines())
    return meta, match.group(2)


def _without_level(body: str) -> str:
    return re.sub(r"## Your level\n.*?(?=\n## )", "", body, count=1, flags=re.DOTALL)


def test_old_agent_is_gone():
    assert not (AGENTS / "ticket-dev.md").exists()


@pytest.mark.parametrize("tier", TIERS)
def test_frontmatter(tier):
    model, effort = TIERS[tier]
    meta, body = _split(f"ticket-dev-{tier}")
    assert meta["name"] == f"ticket-dev-{tier}"
    assert meta["model"] == model
    assert meta["effort"] == effort
    assert meta["description"]
    assert "## Your level" in body


def test_bodies_identical_outside_level():
    bodies = {t: _without_level(_split(f"ticket-dev-{t}")[1]) for t in TIERS}
    assert bodies["godzilla"] == bodies["workhorse"] == bodies["pawn"]


@pytest.mark.parametrize("tier", TIERS)
def test_both_prefixes_documented(tier):
    body = _split(f"ticket-dev-{tier}")[1]
    assert "`tier too low: `" in body
    assert "`verification failed: `" in body


def test_pawn_level_is_literal():
    level = _split("ticket-dev-pawn")[1].split("## Your level")[1].split("\n## ")[0]
    assert "tier too low: " in level
