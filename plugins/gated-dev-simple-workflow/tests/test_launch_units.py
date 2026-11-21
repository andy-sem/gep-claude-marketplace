"""Units of the launcher (gated_dev.launch)."""

import json
import re
from pathlib import Path

import pytest

from gated_dev.errors import LaunchError
from gated_dev.launch.cli import LaunchCli
from gated_dev.launch.naming import LaunchNaming
from gated_dev.launch.orca import OrcaWorktrees
from gated_dev.launch.terminal import TerminalCommands
from gated_dev.launch.ticket_project import TicketProject

FIXTURES = Path(__file__).parent / "fixtures"


def project(tmp_path, *, config=None, tickets=None):
    """The JS fixture `repo({config, tickets})` without git: .claude/gated-dev.json and ticket files."""
    if config is not None:
        (tmp_path / ".claude").mkdir(parents=True, exist_ok=True)
        (tmp_path / ".claude" / "gated-dev.json").write_text(config if isinstance(config, str) else json.dumps(config))
    for key, text in (tickets or {}).items():
        (tmp_path / "docs" / "tickets" / key).mkdir(parents=True, exist_ok=True)
        (tmp_path / "docs" / "tickets" / key / "ticket.md").write_text(text)
    return tmp_path


# --- names and commands -------------------------------------------------------


def test_build_shell_command_quotes_cwd_sets_key_and_names_the_session():
    assert (
        TerminalCommands.build_shell_command(cwd="/a b/c", key="PROJ-1", args=["--resume"])
        == """cd '/a b/c' && TICKET_FLOW_KEY=PROJ-1 claude --name "PROJ-1 resume" "/ticket PROJ-1 --resume\""""
    )
    assert (
        TerminalCommands.build_shell_command(cwd="/x", key="PROJ-1", summary="Fix it", remote_control=True)
        == """cd '/x' && TICKET_FLOW_KEY=PROJ-1 claude --name "PROJ-1 · Fix it" --remote-control "PROJ-1 · Fix it" "/ticket PROJ-1\""""
    )


def test_build_shell_command_escapes_single_quotes_in_cwd():
    command = TerminalCommands.build_shell_command(cwd="/it's/a\"b\\c", key="K-1")
    assert re.match(r"^cd '/it'\\''s/a\"b\\c' &&", command)


@pytest.mark.parametrize("key", ["", "a b", "K;rm", "K/1", "a..b", "$(x)", "-K"])
def test_build_shell_command_rejects_unsafe_keys(key):
    with pytest.raises(LaunchError, match="Invalid ticket key"):
        TerminalCommands.build_shell_command(cwd="/x", key=key)


@pytest.mark.parametrize(
    ("opts", "message"),
    [
        ({"cwd": "x", "key": "K-1"}, "absolute"),
        ({"cwd": "/x\n", "key": "K-1"}, "absolute"),
        ({"cwd": "/x", "key": "K-1", "args": ["--yolo"]}, "not allowed"),
        ({"cwd": "/x", "key": "K-1", "remote_control": "yes"}, "boolean"),
    ],
)
def test_build_shell_command_rejects_other_args_relative_cwd_bad_remote_control(opts, message):
    with pytest.raises(LaunchError, match=message):
        TerminalCommands.build_shell_command(**opts)


def test_short_summary_strips_unsafe_characters_and_cuts_at_a_word_boundary():
    assert LaunchNaming.short_summary('Say "hi" $(rm -rf /) `x` \\ !') == "Say hi (rm -rf /) x"
    assert LaunchNaming.short_summary(None) == ""
    assert LaunchNaming.short_summary("Export reports as CSV with filters and pagination support") == "Export reports as CSV with filters and"
    assert LaunchNaming.short_summary("a" * 50) == "a" * 40


def test_session_name_key_resume_and_summary():
    assert LaunchNaming.session_name(key="K-1") == "K-1"
    assert LaunchNaming.session_name(key="K-1", args=["--resume"]) == "K-1 resume"
    assert LaunchNaming.session_name(key="K-1", summary="Do it!") == "K-1 · Do it"


def test_a_hostile_title_cannot_reach_the_shell_or_applescript():
    summary = "\"; do shell script \"x\" `whoami` $HOME '"
    command = TerminalCommands.build_shell_command(cwd="/x", key="K-1", summary=summary)
    assert command.count('"') == 4
    assert not re.search(r"[`$']", command[len("cd '/x' ") :])
    script = TerminalCommands.build_apple_script(command=command, key="K-1", summary=summary)
    name_lines = [line for line in script.split("\n") if "set name to" in line]
    assert name_lines
    for line in name_lines:
        assert re.match(r'^set name to "[^"\\]*"$', line.strip())


def test_slugify_follows_the_skill_rule():
    assert LaunchNaming.slugify("Add slugify helper, and drop the legacy folder") == "add-slugify-helper-and-drop-the-legacy-f"
    assert LaunchNaming.slugify("  --Hello  World--  ") == "hello-world"
    assert LaunchNaming.slugify("!!!") == "work"
    assert LaunchNaming.slugify("a" * 39 + " b") == "a" * 39


@pytest.mark.parametrize(
    ("env", "host"),
    [
        ({"TERM_PROGRAM": "Orca"}, "orca"),
        ({"TERM_PROGRAM": "iTerm.app"}, "iterm"),
        ({"ORCA_TERMINAL_HANDLE": "t1"}, "orca"),
        ({"ITERM_SESSION_ID": "w0t0p0:X"}, "iterm"),
        ({"TERM_PROGRAM": "iTerm.app", "ORCA_TERMINAL_HANDLE": "t1"}, "iterm"),
        ({"TERM_PROGRAM": "Orca", "ITERM_SESSION_ID": "w0t0p0:X"}, "orca"),
        ({"TERM_PROGRAM": "Apple_Terminal"}, None),
        ({}, None),
    ],
)
def test_detect_host_term_program_first_then_orca_handle_then_iterm_session(env, host):
    assert TerminalCommands.detect_host(env) == host


@pytest.mark.parametrize(
    ("env", "guid"),
    [
        ({"ITERM_SESSION_ID": "w0t1p0:AB-12"}, "AB-12"),
        ({"ITERM_SESSION_ID": "garbage"}, None),
        ({"ITERM_SESSION_ID": 'w0:a"b'}, None),
        ({}, None),
    ],
)
def test_iterm_session_id_takes_the_guid_and_ignores_unusable_values(env, guid):
    assert TerminalCommands.iterm_session_id(env) == guid


def test_build_applescript_escapes_names_the_tab_and_targets_the_launchers_window():
    assert LaunchNaming.apple_script_string('a"b\\c') == '"a\\"b\\\\c"'
    script = TerminalCommands.build_apple_script(command="cd '/x' && echo \"hi\"", key="K-1", session_id="S-1")
    assert re.search(r'set name to "K-1"', script)
    assert re.search(r"write text \"cd '/x' && echo \\\"hi\\\"\"", script)
    assert re.search(r'if id of s is "S-1" then', script)
    assert not re.search(r"repeat with w", TerminalCommands.build_apple_script(command="c", key="K-1"))


def test_build_orca_args_selector_then_launchers_workspace_then_path():
    base = {"cwd": "/r", "command": "c", "key": "K-1"}

    def at(**o):
        return TerminalCommands.build_orca_args(**{**base, **o})[3]

    assert at(selector="id:w1", workspace_id="ws") == "id:w1"
    assert at(workspace_id="ws") == "id:ws"
    assert at() == "path:/r"
    assert TerminalCommands.build_orca_args(**base, summary="T")[4:] == ["--title", "K-1 · T", "--command", "c", "--json"]


def test_orca_worktree_args_name_the_worktree_and_branch_after_key_and_title():
    assert OrcaWorktrees("/r").orca_worktree_args(key="K-1", title="Do it", base="main") == [
        "worktree", "create", "--repo", "path:/r", "--name", "k-1-do-it",
        "--branch", "K-1/do-it", "--base-branch", "origin/main", "--setup", "skip", "--json",
    ]  # fmt: skip


# --- config and tickets -------------------------------------------------------


def test_read_config_defaults_overrides_and_invalid_content(tmp_path):
    def cfg(n, **kw):
        return TicketProject(project(tmp_path / str(n), **kw)).read_config()

    d = cfg("d")
    assert d["ticketsDir"] == "docs/tickets"
    assert d["keyPattern"].search("proj-1")
    assert d["baseBranch"] is None
    assert d["orchestratorRules"] is None
    assert d["tracker"] is None
    assert cfg("r", config={"orchestratorRules": ".claude/rules.md"})["orchestratorRules"] == ".claude/rules.md"
    c = cfg("c", config={"ticketsDir": "t", "keyPattern": "^[A-Z]+-\\d+$", "baseBranch": "develop", "models": {}})
    assert c["ticketsDir"] == "t"
    assert c["baseBranch"] == "develop"
    assert not c["keyPattern"].search("proj-1")
    bad_cases = [
        ("{", "invalid JSON"),
        ("[]", "JSON object"),
        ({"nope": 1}, 'unknown key "nope"'),
        ({"ticketsDir": "../x"}, "ticketsDir"),
        ({"ticketsDir": "/abs"}, "ticketsDir"),
        ({"keyPattern": "("}, "keyPattern"),
        ({"baseBranch": "a b"}, "baseBranch"),
        ({"orchestratorRules": "../rules.md"}, "orchestratorRules"),
        ({"orchestratorRules": "/abs/rules.md"}, "orchestratorRules"),
        ({"orchestratorRules": 3}, "orchestratorRules"),
    ]
    for n, (bad, message) in enumerate(bad_cases):
        with pytest.raises(LaunchError, match=message):
            cfg(f"bad{n}", config=bad)


TRACKER_DEFAULTS = {
    "type": "jira",
    "site": None,
    "statuses": {"inProgress": "In Progress", "inReview": "In Review", "done": "Done"},
    "startFrom": None,
    "assign": True,
    "comments": True,
    "baseFromParent": None,
}


def test_read_config_tracker_defaults(tmp_path):
    config = TicketProject(project(tmp_path, config={"tracker": {"type": "jira"}})).read_config()
    assert config["tracker"] == TRACKER_DEFAULTS
    assert config["keyPattern"].pattern == r"^[A-Z][A-Z0-9]*-\d+$"


def test_read_config_tracker_overrides(tmp_path):
    tracker = {
        "type": "jira",
        "site": "acme.example.net",
        "statuses": {"inProgress": "Doing", "inReview": None},
        "startFrom": ["To Do", "Backlog"],
        "assign": False,
        "comments": False,
        "baseFromParent": "feature/{parent}/*",
    }
    config = TicketProject(project(tmp_path / "a", config={"tracker": tracker})).read_config()
    assert config["tracker"] == {
        **tracker,
        "statuses": {"inProgress": "Doing", "inReview": None, "done": "Done"},
    }
    explicit = TicketProject(project(tmp_path / "b", config={"tracker": {"type": "jira"}, "keyPattern": "^[A-Z]+-\\d+$"})).read_config()
    assert explicit["keyPattern"].pattern == "^[A-Z]+-\\d+$"


@pytest.mark.parametrize(
    ("tracker", "message"),
    [
        ("jira", "tracker.*object"),
        ({}, "type"),
        ({"type": "linear"}, "linear"),
        ({"type": "jira", "nope": 1}, "nope"),
        ({"type": "jira", "statuses": {"nope": "X"}}, "nope"),
        ({"type": "jira", "statuses": {"inProgress": None}}, "inProgress"),
        ({"type": "jira", "statuses": {"inProgress": ""}}, "inProgress"),
        ({"type": "jira", "statuses": {"done": None}}, "done"),
        ({"type": "jira", "statuses": {"done": ""}}, "done"),
        ({"type": "jira", "startFrom": "To Do"}, "startFrom"),
        ({"type": "jira", "startFrom": ["To Do", ""]}, "startFrom"),
        ({"type": "jira", "startFrom": [1]}, "startFrom"),
        ({"type": "jira", "assign": "yes"}, "assign"),
        ({"type": "jira", "comments": 1}, "comments"),
        ({"type": "jira", "site": "https://x"}, "site"),
        ({"type": "jira", "site": "x/y"}, "site"),
        ({"type": "jira", "baseFromParent": "feature/*"}, "baseFromParent"),
        ({"type": "jira", "baseFromParent": "feature/{parent}/a b"}, "baseFromParent"),
        ({"type": "jira", "baseFromParent": "feature/{parent}/$x"}, "baseFromParent"),
    ],
)
def test_read_config_tracker_invalid(tmp_path, tracker, message):
    with pytest.raises(LaunchError, match=message):
        TicketProject(project(tmp_path, config={"tracker": tracker})).read_config()


def test_read_config_without_tracker_is_unchanged(tmp_path):
    config = TicketProject(project(tmp_path, config={"ticketsDir": "t"})).read_config()
    assert config["tracker"] is None
    assert config["keyPattern"].pattern == TicketProject.DEFAULT_KEY_PATTERN
    assert TicketProject(project(tmp_path / "none")).read_config()["tracker"] is None


def test_launch_ticket_with_tracker_and_no_ticket_md_starts_in_the_main_checkout(tmp_path):
    from gated_dev.completed_run import CompletedRun
    from gated_dev.launch.launcher import TicketLauncher

    def fake_run(file, argv):
        return CompletedRun("", "")

    env = {"TERM_PROGRAM": "iTerm.app"}
    config = TicketProject(project(tmp_path / "a", config={"tracker": {"type": "jira"}})).read_config()
    plan = TicketLauncher.launch_ticket(root=tmp_path / "a", key="PROJ-1", config=config, dry_run=True, env=env, run=fake_run)
    assert plan["mode"] == "main-checkout"
    assert plan["summary"] is None
    assert plan["note"] == "no ticket.md yet; the session fetches it from Jira"

    root = project(tmp_path / "b", config={"tracker": {"type": "jira"}}, tickets={"PROJ-1": "# Fix it\n"})
    config = TicketProject(root).read_config()
    plan = TicketLauncher.launch_ticket(root=root, key="PROJ-1", config=config, dry_run=True, env=env, run=fake_run)
    assert plan["mode"] == "main-checkout"
    assert plan["summary"] == "Fix it"
    assert plan["note"] is None


def test_check_key_applies_key_pattern_and_the_safe_character_set(tmp_path):
    strict = TicketProject(project(tmp_path / "strict", config={"keyPattern": "^[A-Z]+-\\d+$"})).read_config()
    assert TicketProject.check_key("PROJ-1", strict) is None
    with pytest.raises(LaunchError, match="not a valid ticket key"):
        TicketProject.check_key("proj-1", strict)
    loose = TicketProject(project(tmp_path / "loose", config={"keyPattern": "."})).read_config()
    for key in ("a;b", "a..b"):
        with pytest.raises(LaunchError, match="not a valid"):
            TicketProject.check_key(key, loose)


def test_read_ticket_title_front_matter_base_missing_file_and_missing_title(tmp_path):
    root = project(
        tmp_path,
        tickets={
            "K-1": "---\nbase: release/2.x\nowner: me\n---\n\n# Export CSV\n\nText",
            "K-2": "# Plain\n",
            "K-3": "no heading\n",
            "K-4": "---\nbase: 'a b'\n---\n# T\n",
            "K-5": '---\nbase: "dev"\n---\n# T\n',
        },
    )
    config = TicketProject(root).read_config()

    def read(key):
        return TicketProject(root).read_ticket(key=key, config=config)

    t = read("K-1")
    assert t["title"] == "Export CSV"
    assert t["base"] == "release/2.x"
    assert read("K-2")["base"] is None
    with pytest.raises(LaunchError, match='no "# " title'):
        read("K-3")
    with pytest.raises(LaunchError, match="no ticket file"):
        read("K-9")
    with pytest.raises(LaunchError, match="invalid base"):
        read("K-4")
    assert read("K-5")["base"] == "dev"


def test_list_ticket_keys_lists_ticket_dirs_whose_key_matches(tmp_path):
    root = project(
        tmp_path / "a",
        config={"keyPattern": "^[A-Z]+-\\d+$"},
        tickets={"K-2": "# a", "K-1": "# b", "notes": "# c"},
    )
    (root / "docs/tickets/K-3").mkdir()
    assert TicketProject(root).list_ticket_keys(config=TicketProject(root).read_config()) == ["K-1", "K-2"]
    empty = project(tmp_path / "b")
    assert TicketProject(empty).list_ticket_keys(config=TicketProject(empty).read_config()) == []


# --- CLI arguments --------------------------------------------------------------


def test_parse_args_keys_or_all_flags_errors():
    assert LaunchCli.parse_args(["-n", "--remote-control", "A-1", "B-2"]) == {
        "keys": ["A-1", "B-2"], "all": False, "dryRun": True, "remoteControl": True, "cwd": None, "help": False,
    }  # fmt: skip
    assert LaunchCli.parse_args(["--all", "--cwd", "/r"])["cwd"] == "/r"
    assert LaunchCli.parse_args(["--help"])["help"]
    for argv, message in [
        ([], "keys or --all"),
        (["--all", "A-1"], "keys or --all"),
        (["--force", "A-1"], "unknown option"),
        (["--cwd"], "needs a directory"),
    ]:
        with pytest.raises(LaunchError, match=message):
            LaunchCli.parse_args(argv)



# --- helpers pinned against the JS implementation (generated once, incl. non-ASCII) ---------

HELPERS = json.loads((FIXTURES / "launch_helpers.json").read_text(encoding="utf-8"))
HELPER_FUNCS = {
    "slugify": LaunchNaming.slugify,
    "shortSummary": LaunchNaming.short_summary,
    "shellQuote": LaunchNaming.shell_quote,
    "appleScriptString": LaunchNaming.apple_script_string,
    "sessionName": lambda value: LaunchNaming.session_name(**value),
}


@pytest.mark.parametrize("row", HELPERS, ids=lambda r: f"{r['fn']}-{json.dumps(r['input'], ensure_ascii=True)[:30]}")
def test_helpers_match_the_js_implementation(row):
    assert HELPER_FUNCS[row["fn"]](row["input"]) == row["expected"]
