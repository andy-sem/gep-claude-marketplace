"""Contract: the launcher CLI (port of the launch.test.mjs rows that inject `run`/`fs`).

Real git repositories with a bare origin; `orca` and `osascript` are recording fakes on a PATH that
holds nothing else but git.
"""

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

from testkit.envs import IsolatedEnv
from testkit.fakebin import FakeBin
from testkit.gitrepo import GitRepo

ORCA = {"TERM_PROGRAM": "Orca"}
ITERM = {"TERM_PROGRAM": "iTerm.app", "ITERM_SESSION_ID": "w0t1p0:ABC-123"}
HOST_VARS = ("TERM_PROGRAM", "ITERM_SESSION_ID")
TERMINAL_OK = '{"result":{"handle":"h1"}}'


@dataclass
class Result:
    status: int
    stdout: str
    stderr: str


class Project:
    """The JS fixtures `repo(...)` and `demo(...)`: a git checkout with config, tickets and fake bins."""

    def __init__(self, tmp: Path, *, config=None, tickets=None, origin=True, branch="main"):
        self.tmp = tmp
        self.home = tmp / "home"
        self.root = GitRepo.init_repo(tmp / "repo", origin=tmp / "origin.git" if origin else None, branch=branch)
        if config is not None:
            (self.root / ".claude").mkdir(exist_ok=True)
            (self.root / ".claude" / "gated-dev.json").write_text(config if isinstance(config, str) else json.dumps(config))
        for key, text in (tickets or {}).items():
            (self.root / "docs" / "tickets" / key).mkdir(parents=True, exist_ok=True)
            (self.root / "docs" / "tickets" / key / "ticket.md").write_text(text)
        self.fb = FakeBin(tmp / "fake")
        self.fb.link("git")
        self.wt_path = tmp / "orca-wt"  # where the fake `orca worktree create` says the worktree is

    # fakes -------------------------------------------------------------------

    def orca(self, *, registered=True, create_out=None, terminal_out=TERMINAL_OK, routes=()):
        create_out = create_out if create_out is not None else {"result": {"worktree": {"id": "w9", "path": str(self.wt_path)}}}
        self.wt_path.mkdir(exist_ok=True)
        defaults = [
            {"match": ["repo", "show"], "stdout": "{}"} if registered else {"match": ["repo", "show"], "status": 1, "stderr": "unknown repo"},
            {"match": ["worktree", "create"], "stdout": create_out if isinstance(create_out, str) else json.dumps(create_out)},
            {"match": ["terminal", "create"], "stdout": terminal_out},
            {"match": ["terminal", "rename"]},
        ]
        by_match = {tuple(r["match"]): r for r in defaults}
        for r in routes:
            by_match[tuple(r["match"])] = r
        self.fb.add("orca", routes=list(by_match.values()))

    def osascript(self):
        self.fb.add("osascript")

    # git ---------------------------------------------------------------------

    def run_dir(self, name: str, branch: str, stage: str | None = None, ticket: str | None = None, key="K-1") -> Path:
        """A worktree of the repo on `branch` (a run), with its state.json stage and ticket.md."""
        wt = GitRepo.add_worktree(self.root, self.tmp / "wts" / name, branch)
        (wt / "docs" / "tickets" / key).mkdir(parents=True, exist_ok=True)
        if stage:
            (wt / "docs" / "tickets" / key / "state.json").write_text(json.dumps({"stage": stage}))
        if ticket is not None:
            (wt / "docs" / "tickets" / key / "ticket.md").write_text(ticket)
        return wt

    def worktrees(self) -> int:
        return GitRepo.git(self.root, "worktree", "list", "--porcelain").count("worktree ")

    @property
    def fetched(self) -> bool:
        return (self.root / ".git" / "FETCH_HEAD").exists()

    # runs --------------------------------------------------------------------

    def launch(self, impl, *args: str, host: dict | None = None, cwd=True) -> Result:
        env = {k: v for k, v in IsolatedEnv.clean(impl.env()).items() if k not in HOST_VARS and not k.startswith("ORCA_")}
        env.update(GitRepo.git_env(self.home))
        env.update({"PATH": str(self.fb.path), **(host or {})})
        cmd = [*FakeBin.absolute(impl.launch()), *(["--cwd", str(self.root)] if cwd else []), *args]
        proc = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=60, check=False)
        return Result(proc.returncode, proc.stdout, proc.stderr)

    def orca_calls(self) -> list[list[str]]:
        return [c["argv"] for c in self.fb.calls("orca")]


def arg_after(argv: list[str], flag: str) -> str:
    return argv[argv.index(flag) + 1]


def create_call(project: Project) -> list[str]:
    [argv] = [a for a in project.orca_calls() if a[:2] == ["terminal", "create"]]
    return argv


@pytest.fixture
def demo(tmp_path):
    """The default JS `demo()`: ticket K-1 "Do it", Orca knows the repo, origin/HEAD is main."""

    def make(**kw):
        kw.setdefault("tickets", {"K-1": "# Do it\n"})
        p = Project(tmp_path, **kw)
        p.orca()
        p.osascript()
        return p

    return make


# --- findRun ------------------------------------------------------------------


def test_find_run_finds_the_key_worktree_ignores_aborted_runs_rejects_several(impl, tmp_path):
    p = Project(tmp_path, tickets={"K-1": "# Do it\n", "K-2": "# Other\n"})
    a = p.run_dir("k-1-a", "K-1/a", stage="dev", ticket="# Do it\n")
    p.run_dir("k-1-b", "K-1/b", stage="aborted")
    p.run_dir("k-10-x", "K-10/x", stage="dev", key="K-10")
    r = p.launch(impl, "--dry-run", "K-1", host=ITERM)
    assert r.status == 0, r.stderr
    assert r.stdout.startswith("K-1: resume\n")
    assert f"  cwd:     {a}\n" in r.stdout
    other = p.launch(impl, "--dry-run", "K-2", host=ITERM)
    assert other.stdout.startswith("K-2: main-checkout\n")

    p.run_dir("k-1-c", "K-1/c", stage="dev")
    two = p.launch(impl, "--dry-run", "K-1", host=ITERM)
    assert two.status == 1
    assert re.search(r"K-1: K-1: several runs \(K-1/a, K-1/c\)", two.stderr)
    assert two.stdout == ""


# --- resolveBase --------------------------------------------------------------


def base_of(p: Project, impl) -> tuple[str, str]:
    r = p.launch(impl, "--dry-run", "K-1", host=ORCA)
    assert r.status == 0, r.stderr
    base = re.search(r"^  base:    (.+)$", r.stdout, re.MULTILINE).group(1)
    command = re.search(r"^  command: (.+)$", r.stdout, re.MULTILINE).group(1)
    return base, command


def test_resolve_base_front_matter_config_origin_head_main(impl, tmp_path):
    fm = Project(tmp_path / "a", config={"baseBranch": "dev"}, tickets={"K-1": "---\nbase: rel\n---\n# T\n"})
    fm.orca()
    base, command = base_of(fm, impl)
    assert base == "rel"
    assert "--base-branch origin/rel" in command

    cfg = Project(tmp_path / "b", config={"baseBranch": "dev"}, tickets={"K-1": "# T\n"})
    cfg.orca()
    assert base_of(cfg, impl)[0] == "dev"

    head = Project(tmp_path / "c", tickets={"K-1": "# T\n"}, branch="trunk")
    head.orca()
    assert base_of(head, impl)[0] == "trunk"

    none = Project(tmp_path / "d", tickets={"K-1": "# T\n"}, origin=False)
    none.orca()
    assert base_of(none, impl)[0] == "main"


# --- createOrcaWorktree ---------------------------------------------------------


def test_create_orca_worktree_copies_local_settings_and_the_ticket(impl, demo):
    p = demo()
    (p.root / ".claude").mkdir(exist_ok=True)
    (p.root / ".claude" / "settings.local.json").write_text('{"a":1}')
    r = p.launch(impl, "K-1", host=ORCA)
    assert r.status == 0, r.stderr
    assert (p.wt_path / ".claude" / "settings.local.json").read_text() == '{"a":1}'
    assert (p.wt_path / "docs/tickets/K-1/ticket.md").read_text() == "# Do it\n"
    argv = next(a for a in p.orca_calls() if a[:2] == ["worktree", "create"])
    assert argv == [
        "worktree", "create", "--repo", f"path:{p.root}", "--name", "k-1-do-it",
        "--branch", "K-1/do-it", "--base-branch", "origin/main", "--setup", "skip", "--json",
    ]  # fmt: skip
    assert create_call(p)[3] == "id:w9"


def test_create_orca_worktree_keeps_a_ticket_the_base_branch_carries_reads_other_json_shapes(impl, demo):
    p = demo(tickets={"K-1": "# New\n"})
    p.orca(create_out={"path": str(p.wt_path)})
    (p.wt_path / "docs/tickets/K-1").mkdir(parents=True)
    (p.wt_path / "docs/tickets/K-1/ticket.md").write_text("# Committed\n")
    r = p.launch(impl, "K-1", host=ORCA)
    assert r.status == 0, r.stderr
    assert create_call(p)[3] == f"path:{p.wt_path}"
    assert (p.wt_path / "docs/tickets/K-1/ticket.md").read_text() == "# Committed\n"
    assert not (p.wt_path / ".claude/settings.local.json").exists()


@pytest.mark.parametrize(
    ("stdout", "message"),
    [("oops", "no JSON"), ('{"result":{}}', "no worktree path"), ('{"path":"rel"}', "no worktree path")],
)
def test_create_orca_worktree_rejects_output_without_json_or_without_a_path(impl, demo, stdout, message):
    p = demo()
    p.orca(create_out=stdout)
    r = p.launch(impl, "K-1", host=ORCA)
    assert r.status == 1
    assert re.search(message, r.stderr)
    assert not [a for a in p.orca_calls() if a[0] == "terminal"]


# --- launchTab ------------------------------------------------------------------


def test_launch_tab_in_iterm_runs_osascript_with_e_lines_targeting_the_launchers_session(impl, demo):
    p = demo()
    r = p.launch(impl, "K-1", host=ITERM)
    assert r.status == 0, r.stderr
    [call] = p.fb.calls("osascript")
    argv = call["argv"]
    assert argv
    assert all(a == "-e" for a in argv[::2])
    assert '\t\t\t\tif id of s is "ABC-123" then' in argv


def test_launch_tab_in_orca_creates_the_terminal_then_renames_it(impl, demo):
    p = demo(tickets={})
    wt = p.run_dir("k-1-do-it", "K-1/do-it", stage="dev", ticket="# Do it\n")
    p.orca(terminal_out='{"result":{"terminal":{"handle":"h1"}}}')
    r = p.launch(impl, "K-1", host=ORCA)
    assert r.status == 0, r.stderr
    calls = p.orca_calls()
    assert [c[:2] for c in calls] == [["terminal", "create"], ["terminal", "rename"]]
    assert calls[0][3] == f"path:{wt}"
    assert calls[1][2:] == ["--terminal", "h1", "--title", "K-1 resume · Do it"]


def test_launch_tab_in_orca_no_handle_means_no_rename_a_failed_rename_is_only_logged(impl, demo, tmp_path):
    quiet = demo()
    quiet.orca(registered=False, terminal_out="not json")
    r = quiet.launch(impl, "K-1", host=ORCA)
    assert r.status == 0, r.stderr
    assert [c[:2] for c in quiet.orca_calls() if c[0] == "terminal"] == [["terminal", "create"]]

    sub = tmp_path / "failing"
    failing = Project(sub, tickets={"K-1": "# Do it\n"})
    failing.orca(registered=False, terminal_out='{"handle":"h1"}', routes=[{"match": ["terminal", "rename"], "status": 1, "stderr": "nope"}])
    r = failing.launch(impl, "K-1", host=ORCA)
    assert r.status == 0
    assert re.search(r"could not rename", r.stderr)


# --- launchTicket ---------------------------------------------------------------


def test_launch_ticket_in_orca_fetch_orca_worktree_tab_in_that_worktree(impl, demo):
    p = demo()
    assert not p.fetched
    r = p.launch(impl, "K-1", host=ORCA)
    assert r.status == 0, r.stderr
    assert re.search(r"^K-1: orca-worktree \(opened\)$", r.stdout, re.MULTILINE)
    assert re.search(r"^  base:    main$", r.stdout, re.MULTILINE)
    assert f"  cwd:     {p.wt_path}\n" in r.stdout
    assert p.fetched
    seq = [c[:2] for c in p.orca_calls()]
    assert seq == [["repo", "show"], ["worktree", "create"], ["terminal", "create"], ["terminal", "rename"]]
    create = create_call(p)
    assert create[3] == "id:w9"
    assert re.fullmatch(
        rf"""cd '{re.escape(str(p.wt_path))}' && TICKET_FLOW_KEY=K-1 claude --name "K-1 · Do it" "/ticket K-1\"""",
        arg_after(create, "--command"),
    )
    assert (p.wt_path / "docs/tickets/K-1/ticket.md").exists()


def test_launch_ticket_in_orca_uses_front_matter_base_before_config_and_origin_head(impl, demo):
    p = demo(tickets={"K-1": "---\nbase: rel\n---\n# T\n"}, config={"baseBranch": "dev"})
    GitRepo.git(p.root, "push", "-q", "origin", "main:rel")  # the fetch needs the branch
    r = p.launch(impl, "K-1", host=ORCA)
    assert r.status == 0, r.stderr
    assert re.search(r"^  base:    rel$", r.stdout, re.MULTILINE)
    assert "origin/rel" in next(a for a in p.orca_calls() if a[:2] == ["worktree", "create"])


def test_launch_ticket_in_orca_with_an_unregistered_repo_opens_in_the_main_checkout(impl, demo):
    p = demo()
    p.orca(registered=False)
    r = p.launch(impl, "K-1", host={**ORCA, "ORCA_WORKTREE_ID": "ws"})
    assert r.status == 0, r.stderr
    assert r.stdout.startswith("K-1: main-checkout (opened)\n")
    assert f"  cwd:     {p.root}\n" in r.stdout
    assert re.search(r"not an Orca repo", r.stdout)
    calls = p.orca_calls()
    assert not [c for c in calls if c[0] == "worktree"]
    assert not p.fetched
    assert next(c for c in calls if c[0] == "terminal")[3] == "id:ws"


def test_launch_ticket_in_iterm_opens_the_main_checkout_and_runs_only_osascript(impl, demo):
    p = demo()
    r = p.launch(impl, "--remote-control", "K-1", host=ITERM)
    assert r.status == 0, r.stderr
    assert r.stdout.startswith("K-1: main-checkout (opened)\n")
    assert '--remote-control "K-1 · Do it"' in r.stdout
    assert {c["name"] for c in p.fb.calls()} == {"osascript"}
    assert not p.fetched


def test_launch_ticket_resumes_an_existing_run_in_its_worktree(impl, demo):
    p = demo(tickets={})
    wt = p.run_dir("k-1-do-it", "K-1/do-it", stage="dev", ticket="# Do it\n")
    r = p.launch(impl, "K-1", host=ORCA)
    assert r.status == 0, r.stderr
    assert r.stdout.startswith("K-1: resume (opened)\n")
    assert f"  cwd:     {wt}\n" in r.stdout
    assert "  title:   K-1 resume · Do it\n" in r.stdout
    create = create_call(p)
    assert create[3] == f"path:{wt}"
    assert re.search(r'"/ticket K-1 --resume"$', arg_after(create, "--command"))


def test_launch_ticket_resumes_a_finished_run_and_restarts_the_pr_watch(impl, demo):
    p = demo()
    wt = p.run_dir("k-1-x", "K-1/x", stage="done")
    r = p.launch(impl, "--dry-run", "K-1", host=ITERM)
    assert r.status == 0, r.stderr
    assert r.stdout.startswith("K-1: resume\n")
    assert f"  cwd:     {wt}\n" in r.stdout
    assert re.search(r'^  command: .*"/ticket K-1 --resume"$', r.stdout, re.MULTILINE)
    assert re.search(r"^  note:    .*PR watch", r.stdout, re.MULTILINE)
    assert p.fb.calls("osascript") == []


def test_launch_ticket_dry_run_changes_nothing_and_plans_the_orca_worktree(impl, demo):
    p = demo()
    r = p.launch(impl, "--dry-run", "K-1", host=ORCA)
    assert r.status == 0, r.stderr
    assert r.stdout.startswith("K-1: orca-worktree\n")
    assert re.search(
        r"^  command: orca worktree create --repo path:\S+ --name k-1-do-it --branch K-1/do-it --base-branch origin/main", r.stdout, re.MULTILINE
    )
    assert [c[:2] for c in p.orca_calls()] == [["repo", "show"]]
    assert p.fb.calls("osascript") == []
    assert not p.fetched
    assert p.worktrees() == 1


def test_launch_ticket_outside_orca_and_iterm_fails_unless_it_is_a_dry_run(impl, demo):
    p = demo()
    r = p.launch(impl, "K-1", host={})
    assert r.status == 1
    assert re.search(r"Orca or iTerm2", r.stderr)
    assert p.fb.calls("orca") == [] and p.fb.calls("osascript") == []
    dry = p.launch(impl, "--dry-run", "K-1", host={})
    assert dry.status == 0, dry.stderr
    assert dry.stdout.startswith("K-1: main-checkout\n  host:    none (dry run only)\n")


def test_launch_ticket_a_failing_orca_worktree_create_throws_and_never_falls_back(impl, demo):
    p = demo()
    p.orca(routes=[{"match": ["worktree", "create"], "status": 1, "stderr": "boom"}])
    r = p.launch(impl, "K-1", host=ORCA)
    assert r.status == 1
    assert re.search(r"boom", r.stderr)
    assert not [c for c in p.orca_calls() if c[0] == "terminal"]
    assert p.fb.calls("osascript") == []


def test_launch_ticket_rejects_a_key_outside_key_pattern_and_a_ticket_without_a_file(impl, demo):
    p = demo(config={"keyPattern": "^[A-Z]+-\\d+$"})
    r = p.launch(impl, "k-1", "K-2", host=ITERM)
    assert r.status == 1
    assert re.search(r"k-1: .*not a valid", r.stderr)
    assert re.search(r"K-2: .*no ticket file", r.stderr)
    assert p.fb.calls("osascript") == []


def test_launch_ticket_with_orchestrator_rules_starts_a_ticket_without_ticket_md_in_the_main_checkout(impl, demo):
    p = demo(config={"orchestratorRules": ".claude/rules.md"})
    for host in (ORCA, ITERM):
        r = p.launch(impl, "--dry-run", "K-2", host=host)
        assert r.status == 0, r.stderr
        assert r.stdout.startswith("K-2: main-checkout\n")
        assert f"  cwd:     {p.root}\n" in r.stdout
        assert "  title:   K-2\n" in r.stdout
        assert re.search(r'^  command: .*"/ticket K-2"$', r.stdout, re.MULTILINE)
        assert re.search(r"^  note:    .*intake", r.stdout, re.MULTILINE)
    assert not [c for c in p.orca_calls() if c[0] == "worktree"]
    # A ticket that has its file still goes the normal way.
    normal = p.launch(impl, "--dry-run", "K-1", host=ORCA)
    assert normal.stdout.startswith("K-1: orca-worktree\n")


# --- tracker ----------------------------------------------------------------------

TRACKER_CONFIG = {"tracker": {"type": "jira"}}


def test_dry_run_tracker_key_without_ticket_file(impl, tmp_path):
    p = Project(tmp_path, config=TRACKER_CONFIG)
    p.orca()
    p.osascript()
    r = p.launch(impl, "--dry-run", "PROJ-7", host=ORCA)
    assert r.status == 0, r.stderr
    assert r.stdout.startswith("PROJ-7: main-checkout\n")
    assert re.search(r"^  note:    .*Jira", r.stdout, re.MULTILINE)
    assert p.fb.calls("orca") == [] and p.fb.calls("osascript") == []


def test_dry_run_tracker_rejects_non_jira_key(impl, tmp_path):
    p = Project(tmp_path, config=TRACKER_CONFIG)
    p.orca()
    r = p.launch(impl, "--dry-run", "add-csv", host=ORCA)
    assert r.status == 1
    assert re.search(r"add-csv: .*not a valid ticket key", r.stderr)
    assert "keyPattern ^[A-Z][A-Z0-9]*-\\d+$" in r.stderr
    assert r.stdout == ""


def test_invalid_tracker_config_exits_1(impl, tmp_path):
    p = Project(tmp_path, config={"tracker": {"type": "linear"}})
    r = p.launch(impl, "--dry-run", "PROJ-7", host=ORCA)
    assert r.status == 1
    assert "tracker.type" in r.stderr


def test_flow_without_tracker_exits_1(impl, tmp_path):
    p = Project(tmp_path, config={"flow": {"max": 2}})
    r = p.launch(impl, "--dry-run", "PROJ-7", host=ORCA)
    assert r.status == 1
    assert "flow requires tracker" in r.stderr
    assert r.stdout == ""


def test_invalid_flow_config_exits_1(impl, tmp_path):
    p = Project(tmp_path, config={"tracker": {"type": "jira"}, "flow": {"pollSeconds": 5}})
    r = p.launch(impl, "--dry-run", "PROJ-7", host=ORCA)
    assert r.status == 1
    assert "flow.pollSeconds" in r.stderr


def test_valid_flow_config_does_not_change_a_tracker_dry_run(impl, tmp_path):
    flow = {"max": 2, "jql": "parent = {parent}", "pollSeconds": 30, "remoteControl": True}
    p = Project(tmp_path, config={"tracker": {"type": "jira"}, "flow": flow})
    p.orca()
    r = p.launch(impl, "--dry-run", "PROJ-7", host=ORCA)
    assert r.status == 0, r.stderr
    assert r.stdout.startswith("PROJ-7: main-checkout\n")


def test_all_with_tracker_lists_only_ticket_files(impl, tmp_path):
    p = Project(tmp_path, config=TRACKER_CONFIG, tickets={"PROJ-1": "# One\n"})
    p.orca()
    r = p.launch(impl, "--all", "--dry-run", host=ITERM)
    assert r.status == 0, r.stderr
    assert r.stdout.startswith("PROJ-1: main-checkout\n")
    assert r.stdout.count(": main-checkout") + r.stdout.count(": orca-worktree") == 1
    assert p.fb.calls("osascript") == []


# --- main -----------------------------------------------------------------------


def test_main_all_dry_run_plans_every_ticket_without_a_run_and_reports_failures_per_key(impl, tmp_path):
    p = Project(tmp_path, tickets={"A-1": "# One\n", "B-2": "# Two\n", "C-3": "no title"})
    p.run_dir("b-2-two", "B-2/two", stage="dev", key="B-2")
    r = p.launch(impl, "--all", "--dry-run", host=ITERM)
    assert r.status == 1
    assert re.search(r"^A-1: main-checkout\n  host:    iterm", r.stdout, re.MULTILINE)
    assert "B-2" not in r.stdout
    assert re.search(r'C-3: .*no "# " title', r.stderr)
    assert p.fb.calls("osascript") == []


def test_main_reports_a_config_error_and_a_usage_error(impl, tmp_path):
    p = Project(tmp_path, config={"bad": 1})
    r = p.launch(impl, "K-1")
    assert r.status == 1
    assert re.search(r'unknown key "bad"', r.stderr)
    usage = p.launch(impl)
    assert usage.status == 2
    assert re.search(r"Usage", usage.stderr)


def test_documented_invocations_run(impl, tmp_path):
    """Every `launch` command line in the skill and the README names the shipped script and runs as a dry run."""
    gd = Path(__file__).resolve().parents[1]
    pattern = re.compile(r'^\s*python3 -I "?(?:\$\{CLAUDE_PLUGIN_ROOT\}|<plugin>)/(scripts/launch\.py)"? ([^#\n]*?)\s*(?:#.*)?$', re.MULTILINE)
    found = []
    for doc in (gd / "skills" / "launch" / "SKILL.md", gd / "README.md"):
        found += [(doc.name, m.group(1), m.group(2).split()) for m in pattern.finditer(doc.read_text())]
    assert len(found) >= 5, found
    keys = {a for _, _, args in found for a in args if not a.startswith("-")}
    p = Project(tmp_path, tickets={k: f"# Ticket {k}\n" for k in keys})
    p.orca()
    p.osascript()
    for name, script, args in found:
        assert (gd / script).is_file()
        r = p.launch(impl, "--dry-run", *[a for a in args if a != "--dry-run"], host=ORCA)
        assert r.status == 0, (name, args, r.stderr)
