"""The `flow.py` commands and flags named in the ticket-flow skill and flow.md exist in FlowCli."""

import re
from pathlib import Path

import pytest

from gated_dev.flow.cli import FlowCli

PLUGIN = Path(__file__).resolve().parents[1]
DOCS = [PLUGIN / "skills/ticket-flow/SKILL.md", PLUGIN / "skills/ticket/references/flow.md"]
SPAN = re.compile(r"flow\.py\"?\s+(\w+)([^`]*)`")
FLAG = re.compile(r"(?<![\w-])(--?[a-z][a-z-]*)")
BOOLEAN = {"--dry-run", "-n", "--remote-control"}


def invocations() -> list[tuple[Path, str, list[str]]]:
    found = []
    for doc in DOCS:
        for match in SPAN.finditer(doc.read_text(encoding="utf-8")):
            found.append((doc, match.group(1), FLAG.findall(match.group(2))))
    return found


def test_the_docs_name_flow_commands():
    commands = {command for _, command, _ in invocations()}
    assert commands == set(FlowCli.COMMANDS)


@pytest.mark.parametrize(("doc", "command", "flags"), invocations(), ids=lambda v: v.name if isinstance(v, Path) else str(v))
def test_command_and_flags_are_accepted(doc, command, flags):
    assert command in FlowCli.COMMANDS
    argv = [command, "--parent", "PROJ-100"]
    if command in ("launch", "skip", "retry"):
        argv.append("PROJ-1")
    for flag in dict.fromkeys(flags):
        assert flag in FlowCli.VALUE_OPTIONS or flag in BOOLEAN, f"{doc.name}: {flag} is not a flow.py option"
        if flag == "--parent":
            continue
        value = {"--mode": "heavy", "--max": "3", "--poll-seconds": "3", "--stale-hours": "3", "--lost-watch-minutes": "3"}.get(flag, "x")
        argv += [flag] if flag in BOOLEAN else [flag, value]
    opts = FlowCli.parse_args(argv)
    assert opts["command"] == command


def test_the_skill_documents_every_command():
    text = DOCS[0].read_text(encoding="utf-8")
    for command in FlowCli.COMMANDS:
        assert f"flow.py\" {command}" in text or f"flow.py {command}" in text


def test_the_skill_passes_the_mode_on_launch():
    text = (PLUGIN / "skills/ticket-flow/SKILL.md").read_text(encoding="utf-8")
    launch = [line for line in text.splitlines() if re.search(r"flow\.py\"? launch", line)]
    assert launch, "the skill has no flow.py launch command"
    assert all("--mode" in line for line in launch)
    assert "modes.md#4-decision-rules-d2" in text
