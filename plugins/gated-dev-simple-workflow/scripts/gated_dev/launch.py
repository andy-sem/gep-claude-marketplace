"""Opens one Claude Code session per ticket, running `/ticket <KEY>`, in a new Orca or iTerm2 tab.

File-based: tickets are `<ticketsDir>/<KEY>/ticket.md`.

    launch.py [--dry-run] [--remote-control] KEY...
    launch.py [--dry-run] [--remote-control] --all

A ticket with a run (a worktree on a `<KEY>/*` branch) is reopened in that worktree with
`--resume` (for a finished run, `stage: done`, that restarts the PR watch, which also cleans
up after a merge). A new ticket gets its own Orca worktree when the host is Orca and the repo
is registered there; otherwise the session starts in the main checkout and the skill creates
the worktree.
"""

import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, NamedTuple

DEFAULT_KEY_PATTERN = "^[A-Za-z][A-Za-z0-9._-]*$"
# Whatever keyPattern says, a key is put into shell commands unquoted.
_SAFE_KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
_SAFE_REF = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]*")
_PLAIN_ARG = re.compile(r"[A-Za-z0-9_:./@-]+")
CONFIG_KEYS = frozenset(
    ("ticketsDir", "keyPattern", "baseBranch", "setupCommand", "formatCommand", "riskPaths", "escalationExtra", "models", "orchestratorRules")
)
ALLOWED_ARGS = frozenset(("--resume",))
MAX_SHORT = 40


class LaunchError(Exception):
    """A launcher failure; the message is what the CLI prints."""


class CompletedRun(NamedTuple):
    stdout: str
    stderr: str


Run = Callable[[str, list[str]], CompletedRun]


def _json(value: Any) -> str:
    """JS `JSON.stringify` for the values that appear in messages."""
    return json.dumps(value, ensure_ascii=False)


def _js_string(value: Any) -> str:
    """JS `String(value)` for JSON-derived values."""
    if value is True:
        return "true"
    if value is False:
        return "false"
    if value is None:
        return "null"
    return str(value)


def _get(obj: Any, key: str) -> Any:
    """`obj?.[key]`: None unless `obj` is a mapping holding the key."""
    return obj.get(key) if isinstance(obj, Mapping) else None


def _first(*values: Any) -> Any:
    """JS `a ?? b ?? c`: the first value that is not None."""
    return next((v for v in values if v is not None), None)


# ---------------------------------------------------------------------------
# Names and commands
# ---------------------------------------------------------------------------


def shell_quote(value: Any) -> str:
    """POSIX single-quote escaping."""
    return "'" + _js_string(value).replace("'", "'\\''") + "'"


def apple_script_string(value: Any) -> str:
    """Escape a string for use inside an AppleScript double-quoted literal."""
    return '"' + _js_string(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


def is_safe_key(key: Any) -> bool:
    """True when `key` is usable in commands, branch and file names."""
    return isinstance(key, str) and _SAFE_KEY.fullmatch(key) is not None and ".." not in key


def short_summary(summary: Any) -> str:
    """A ticket title reduced to a safe, short phrase.

    Every character outside `[A-Za-z0-9 .,:()/_-]` becomes a space (this drops quotes, `$`,
    backticks, backslashes and `!`, so the title is safe in the double quotes of the command
    and in an AppleScript literal), then it is cut at a word boundary. Same rule as section 3
    step 8 of the ticket skill.
    """
    clean = re.sub(r"[^A-Za-z0-9 .,:()/_-]", " ", "" if summary is None else _js_string(summary))
    clean = re.sub(r" +", " ", clean).strip()
    if len(clean) <= MAX_SHORT:
        return clean
    window = clean[:MAX_SHORT]
    if clean[MAX_SHORT] == " ":
        return window
    space = window.rfind(" ")
    return (window[:space] if space > 0 else window).strip()


def session_name(*, key: str, args: Sequence[str] = (), summary: Any = None) -> str:
    """Title of a session: tab title, `claude --name` and the Remote Control name.

    `<KEY> · <summary>` for a new ticket, `<KEY> resume · <summary>` for a run that is resumed;
    without a summary just the key (and purpose).
    """
    head = f"{key} resume" if "--resume" in args else key
    short = short_summary(summary)
    return f"{head} · {short}" if short else head


def slugify(title: Any) -> str:
    """Same rule as section 3 step 3 of the ticket skill."""
    slug = re.sub(r"[^a-z0-9]+", "-", ("" if title is None else _js_string(title)).lower())
    slug = slug.strip("-")[:40].rstrip("-")
    return slug or "work"


def detect_host(env: Mapping[str, str] | None = None) -> str | None:
    """The terminal app the launcher runs in, which is where its sessions open.

    `orca`, `iterm`, or None for anything else. Same rule as section 0 of the ticket skill:
    TERM_PROGRAM decides first, because a terminal started from another one can inherit its
    variables; ORCA_TERMINAL_HANDLE and ITERM_SESSION_ID cover a multiplexer such as tmux.
    """
    env = os.environ if env is None else env
    if env.get("TERM_PROGRAM") == "iTerm.app":
        return "iterm"
    if env.get("TERM_PROGRAM") == "Orca":
        return "orca"
    if env.get("ORCA_TERMINAL_HANDLE"):
        return "orca"
    if env.get("ITERM_SESSION_ID"):
        return "iterm"
    return None


def iterm_session_id(env: Mapping[str, str] | None = None) -> str | None:
    """The GUID in ITERM_SESSION_ID ("w0t1p0:<GUID>"), or None if there is none."""
    env = os.environ if env is None else env
    match = re.fullmatch(r"[^:]*:([0-9A-Za-z-]+)", env.get("ITERM_SESSION_ID") or "")
    return match[1] if match else None


def build_shell_command(*, cwd: Any, key: Any, args: Sequence[str] = (), remote_control: Any = False, summary: Any = None) -> str:
    if not is_safe_key(key):
        raise LaunchError(f"Invalid ticket key: {_json(key)}")
    if not isinstance(cwd, str) or not os.path.isabs(cwd) or re.search(r"[\n\r\0]", cwd):
        raise LaunchError(f"cwd must be an absolute path: {_json(cwd)}")
    for arg in args:
        if arg not in ALLOWED_ARGS:
            raise LaunchError(f"Argument not allowed: {_json(arg)}")
    if not isinstance(remote_control, bool):
        raise LaunchError(f"remoteControl must be a boolean: {_json(remote_control)}")
    prompt = " ".join(["/ticket", key, *args])
    # The title only holds a checked key, a fixed purpose word and a summary reduced to a safe
    # character set, so double quotes are safe. The flags go before the prompt so the prompt
    # stays positional.
    title = session_name(key=key, args=args, summary=summary)
    rc = f'--remote-control "{title}" ' if remote_control else ""
    return f'cd {shell_quote(cwd)} && TICKET_FLOW_KEY={key} claude --name "{title}" {rc}"{prompt}"'


def build_apple_script(*, command: str, key: str, args: Sequence[str] = (), session_id: str | None = None, summary: Any = None) -> str:
    name = session_name(key=key, args=args, summary=summary)
    # Without a match, for example after the launcher's tab was closed, the tab goes to the
    # frontmost window.
    find_window = (
        [
            "\trepeat with w in windows",
            "\t\trepeat with t in tabs of w",
            "\t\t\trepeat with s in sessions of t",
            f"\t\t\t\tif id of s is {apple_script_string(session_id)} then",
            "\t\t\t\t\tset targetId to id of w",
            "\t\t\t\t\tset targetWindow to first window whose id is targetId",
            "\t\t\t\tend if",
            "\t\t\tend repeat",
            "\t\tend repeat",
            "\tend repeat",
        ]
        if session_id
        else []
    )
    return "\n".join(
        [
            'tell application "iTerm2"',
            "\tactivate",
            "\tset targetWindow to missing value",
            *find_window,
            "\tif targetWindow is missing value and (count of windows) > 0 then",
            "\t\tset targetWindow to current window",
            "\tend if",
            "\tif targetWindow is missing value then",
            "\t\tcreate window with default profile",
            "\t\ttell current session of current window",
            f"\t\t\tset name to {apple_script_string(name)}",
            f"\t\t\twrite text {apple_script_string(command)}",
            "\t\tend tell",
            "\telse",
            "\t\ttell targetWindow",
            "\t\t\tcreate tab with default profile",
            "\t\t\ttell current session",
            f"\t\t\t\tset name to {apple_script_string(name)}",
            f"\t\t\t\twrite text {apple_script_string(command)}",
            "\t\t\tend tell",
            "\t\tend tell",
            "\tend if",
            "end tell",
        ]
    )


def build_orca_args(
    *,
    cwd: str,
    command: str,
    key: str,
    args: Sequence[str] = (),
    workspace_id: str | None = None,
    selector: str | None = None,
    summary: Any = None,
) -> list[str]:
    """`selector` names the Orca worktree the tab opens in.

    Without it, `workspace_id` (ORCA_WORKTREE_ID) keeps the tab next to the launcher. The
    session still runs in `cwd`, because the command starts with a cd.
    """
    return [
        "terminal",
        "create",
        "--worktree",
        selector or (f"id:{workspace_id}" if workspace_id else f"path:{cwd}"),
        "--title",
        session_name(key=key, args=args, summary=summary),
        "--command",
        command,
        "--json",
    ]


# ---------------------------------------------------------------------------
# Process and file helpers
# ---------------------------------------------------------------------------


def default_run(file: str, argv: list[str]) -> CompletedRun:
    try:
        proc = subprocess.run([file, *argv], capture_output=True, text=True, check=False)
    except OSError as error:
        raise LaunchError(f"{file} failed: {error}") from error
    if proc.returncode != 0:
        # The orca CLI reports errors as JSON on stdout.
        detail = (proc.stderr or proc.stdout or f"exit status {proc.returncode}").strip()
        raise LaunchError(f"{file} failed: {detail}")
    return CompletedRun(proc.stdout, proc.stderr)


def _terminal_handle(stdout: Any) -> str | None:
    """The terminal handle in the JSON `orca terminal create` prints, or None."""
    try:
        out = json.loads(stdout)
    except (TypeError, ValueError):
        return None
    result = _get(out, "result")
    return _first(_get(_get(result, "terminal"), "handle"), _get(result, "handle"), _get(out, "handle"))


def find_root(*, cwd: str, run: Run = default_run) -> str:
    """The main checkout of the repository `cwd` belongs to."""
    out = run("git", ["-C", cwd, "worktree", "list", "--porcelain"]).stdout
    first = re.search(r"^worktree (.+)$", str(out), re.MULTILINE)
    if not first:
        raise LaunchError(f"{cwd} is not inside a git repository")
    return first[1]


def _outside_repo(path: str) -> bool:
    return os.path.isabs(path) or ".." in re.split(r"[\\/]", path)


def read_config(*, root: str | Path) -> dict:
    """`.claude/gated-dev.json` of `root`, with defaults. Raises on invalid content."""
    file = Path(root) / ".claude" / "gated-dev.json"
    raw: dict = {}
    if file.exists():
        try:
            parsed = json.loads(file.read_text(encoding="utf-8"))
        except ValueError as error:
            raise LaunchError(f"{file}: invalid JSON ({error})") from error
        if not isinstance(parsed, dict):
            raise LaunchError(f"{file}: must contain a JSON object")
        for k in parsed:
            if k not in CONFIG_KEYS:
                raise LaunchError(f'{file}: unknown key "{k}"')
        raw = parsed
    tickets_dir = _first(raw.get("ticketsDir"), "docs/tickets")
    if not isinstance(tickets_dir, str) or not tickets_dir or _outside_repo(tickets_dir):
        raise LaunchError(f"{file}: ticketsDir must be a relative path inside the repo")
    try:
        key_pattern = re.compile(_first(raw.get("keyPattern"), DEFAULT_KEY_PATTERN))
    except (re.error, TypeError) as error:
        raise LaunchError(f"{file}: invalid keyPattern ({error})") from error
    base_branch = raw.get("baseBranch")
    if base_branch is not None and not _SAFE_REF.fullmatch(_js_string(base_branch)):
        raise LaunchError(f"{file}: invalid baseBranch")
    rules = raw.get("orchestratorRules")
    if rules is not None and (not isinstance(rules, str) or not rules or _outside_repo(rules)):
        raise LaunchError(f"{file}: orchestratorRules must be a relative path inside the repo")
    return {"ticketsDir": tickets_dir, "keyPattern": key_pattern, "baseBranch": base_branch, "orchestratorRules": rules}


def check_key(key: Any, config: Mapping) -> None:
    """Checks a key against the safe set and the configured pattern."""
    if not is_safe_key(key) or not config["keyPattern"].search(key):
        raise LaunchError(f"{_json(key)} is not a valid ticket key (keyPattern {config['keyPattern'].pattern})")


_FRONT_MATTER = re.compile(r"---\r?\n(.*?)\r?\n---\r?\n", re.DOTALL)


def read_ticket(*, root: str | Path, key: str, config: Mapping) -> dict:
    """`{file, title, base}` of `<root>/<ticketsDir>/<KEY>/ticket.md`.

    `base` is the front matter `base:` or None. Raises when the file is missing or has no title.
    """
    file = Path(root) / config["ticketsDir"] / key / "ticket.md"
    if not file.exists():
        raise LaunchError(f"{key}: no ticket file at {os.path.relpath(file, root)}")
    text = file.read_text(encoding="utf-8")
    body = text
    base = None
    front = _FRONT_MATTER.match(text)
    if front:
        body = text[front.end() :]
        found = re.search(r"^base:(.*)$", front[1], re.MULTILINE)
        if found:
            value = re.sub(r"""^(["'])(.*)\1$""", r"\2", found[1].strip())
            if not _SAFE_REF.fullmatch(value):
                raise LaunchError(f'{key}: invalid base "{value}"')
            base = value
    title = re.search(r"^# +(.+?)\s*$", body, re.MULTILINE)
    if not title:
        raise LaunchError(f'{key}: ticket.md has no "# " title')
    return {"file": str(file), "title": title[1], "base": base}


def list_ticket_keys(*, root: str | Path, config: Mapping) -> list[str]:
    """Keys of every `<ticketsDir>/<KEY>/ticket.md` in the main checkout."""
    directory = Path(root) / config["ticketsDir"]
    if not directory.exists():
        return []
    return sorted(
        d.name
        for d in directory.iterdir()
        if d.is_dir() and is_safe_key(d.name) and config["keyPattern"].search(d.name) and (d / "ticket.md").exists()
    )


def find_run(*, root: str | Path, key: str, config: Mapping, run: Run = default_run) -> dict | None:
    """The ticket's run: the worktree on a `<KEY>/*` branch, with the `stage` of its `state.json`.

    The stage is None without one. Aborted runs are ignored. Returns None when there is no run;
    raises when several are left.
    """
    out = run("git", ["-C", str(root), "worktree", "list", "--porcelain"]).stdout
    runs = []
    for block in re.split(r"\n\n+", str(out)):
        wt = re.search(r"^worktree (.+)$", block, re.MULTILINE)
        branch = re.search(r"^branch refs/heads/(.+)$", block, re.MULTILINE)
        if not wt or not branch or not branch[1].startswith(f"{key}/"):
            continue
        stage = None
        try:
            state = Path(wt[1]) / config["ticketsDir"] / key / "state.json"
            stage = _get(json.loads(state.read_text(encoding="utf-8")), "stage")
        except (OSError, ValueError):
            pass
        if stage != "aborted":
            runs.append({"path": wt[1], "branch": branch[1], "stage": stage})
    if len(runs) > 1:
        raise LaunchError(f"{key}: several runs ({', '.join(r['branch'] for r in runs)}); open the one you want with /ticket {key} --resume")
    return runs[0] if runs else None


def resolve_base(*, root: str | Path, ticket: Mapping, config: Mapping, run: Run = default_run) -> str:
    """The branch a new ticket starts from.

    Front matter `base:`, config `baseBranch`, the remote default branch, `main` (section 3
    step 2 of the skill).
    """
    if ticket.get("base"):
        return ticket["base"]
    if config.get("baseBranch"):
        return config["baseBranch"]
    try:
        out = run("git", ["-C", str(root), "symbolic-ref", "--short", "refs/remotes/origin/HEAD"]).stdout
        ref = re.sub(r"^origin/", "", str(out).strip())
        if _SAFE_REF.fullmatch(ref):
            return ref
    except LaunchError:
        pass
    return "main"


def orca_has_repo(*, root: str | Path, run: Run = default_run) -> bool:
    """True when Orca knows the repository at `root`."""
    try:
        run("orca", ["repo", "show", "--repo", f"path:{root}", "--json"])
    except LaunchError:
        return False
    return True


def orca_worktree_args(*, root: str | Path, key: str, title: str, base: str) -> list[str]:
    """The arguments of `orca worktree create` for a new ticket."""
    slug = slugify(title)
    return [
        "worktree",
        "create",
        "--repo",
        f"path:{root}",
        "--name",
        f"{key.lower()}-{slug}",
        "--branch",
        f"{key}/{slug}",
        "--base-branch",
        f"origin/{base}",
        "--setup",
        "skip",
        "--json",
    ]


def create_orca_worktree(
    *,
    root: str | Path,
    key: str,
    ticket: Mapping,
    config: Mapping,
    base: str,
    run: Run = default_run,
    log: Callable[[str], None] = lambda line: None,
) -> dict:
    """Creates the ticket's worktree through Orca, copies the local Claude settings and the ticket file into it.

    Returns `{id, path, branch, selector}`.
    """
    argv = orca_worktree_args(root=root, key=key, title=ticket["title"], base=base)
    stdout = run("orca", argv).stdout
    try:
        out = json.loads(stdout)
    except ValueError as error:
        raise LaunchError("orca worktree create printed no JSON") from error
    result = _get(out, "result")
    wt = _first(_get(result, "worktree"), result, out)
    wt_id = _get(wt, "id")
    wt_path = _first(_get(wt, "path"), _get(_get(wt, "git"), "path"))
    if not isinstance(wt_path, str) or not os.path.isabs(wt_path):
        raise LaunchError("orca worktree create returned no worktree path")

    def copy(source: str | Path, target: Path, what: str) -> None:
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
        except OSError:
            # Path only: the settings file may hold permissions or secrets.
            log(f"{key}: could not copy {what} to {target}")

    settings = Path(root) / ".claude" / "settings.local.json"
    if settings.exists():
        copy(settings, Path(wt_path) / ".claude" / "settings.local.json", "settings.local.json")
    # The session reads the ticket from its own checkout; the base branch may not carry it.
    ticket_target = Path(wt_path) / config["ticketsDir"] / key / "ticket.md"
    if not ticket_target.exists():
        copy(ticket["file"], ticket_target, "ticket.md")
    return {
        "id": wt_id,
        "path": wt_path,
        "branch": argv[argv.index("--branch") + 1],
        "selector": f"id:{wt_id}" if wt_id else f"path:{wt_path}",
    }


# ---------------------------------------------------------------------------
# Launching
# ---------------------------------------------------------------------------


def launch_tab(
    *,
    host: str | None,
    cwd: str,
    key: str,
    args: Sequence[str] = (),
    remote_control: bool = False,
    summary: Any = None,
    selector: str | None = None,
    env: Mapping[str, str] | None = None,
    run: Run = default_run,
    log: Callable[[str], None] = lambda line: None,
) -> dict:
    """Opens one tab running the session command.

    `host` is `orca` or `iterm`; `selector` is the Orca worktree to open the tab in (Orca only).
    Returns `{command, title}`.
    """
    env = os.environ if env is None else env
    title = session_name(key=key, args=args, summary=summary)
    command = build_shell_command(cwd=cwd, key=key, args=args, remote_control=remote_control, summary=summary)
    if host == "orca":
        created = run(
            "orca",
            build_orca_args(
                cwd=cwd,
                command=command,
                key=key,
                args=args,
                workspace_id=env.get("ORCA_WORKTREE_ID"),
                selector=selector,
                summary=summary,
            ),
        )
        # Orca retitles a tab that runs Claude, so set the title once more.
        handle = _terminal_handle(created.stdout if created else None)
        if handle:
            try:
                run("orca", ["terminal", "rename", "--terminal", handle, "--title", title])
            except LaunchError as error:
                log(f"{key}: could not rename the tab ({error})")
    elif host == "iterm":
        script = build_apple_script(command=command, key=key, args=args, session_id=iterm_session_id(env), summary=summary)
        run("osascript", [part for line in script.split("\n") for part in ("-e", line)])
    else:
        raise LaunchError(f"unknown host {_json(host)}")
    return {"command": command, "title": title}


def launch_ticket(
    *,
    root: str | Path,
    key: str,
    config: Mapping,
    remote_control: bool = False,
    dry_run: bool = False,
    env: Mapping[str, str] | None = None,
    run: Run = default_run,
    log: Callable[[str], None] = lambda line: None,
) -> dict:
    """Plans and (unless `dry_run`) opens the session for one ticket.

    Returns `{key, mode, host, cwd, command, title, base, worktree, note, launched}` where
    `mode` is `resume`, `orca-worktree` or `main-checkout`. A dry run calls only read-only
    commands (`git worktree list`, `git symbolic-ref`, `orca repo show`).
    """
    env = os.environ if env is None else env
    root = str(root)
    check_key(key, config)
    host = detect_host(env)
    if not host and not dry_run:
        raise LaunchError(f"open sessions from Orca or iTerm2 (TERM_PROGRAM={env.get('TERM_PROGRAM', 'unset')}); --dry-run works anywhere")
    base: dict = {"key": key, "host": host, "base": None, "worktree": None, "note": None}

    def open_session(plan: dict) -> dict:
        result = {**base, **plan, "launched": False}
        result["title"] = session_name(key=key, args=plan["args"], summary=plan["summary"])
        result["command"] = build_shell_command(
            cwd=plan["cwd"], key=key, args=plan["args"], remote_control=remote_control, summary=plan["summary"]
        )
        if dry_run:
            return result
        launch_tab(
            host=host,
            cwd=plan["cwd"],
            key=key,
            args=plan["args"],
            remote_control=remote_control,
            summary=plan["summary"],
            selector=plan.get("selector"),
            env=env,
            run=run,
            log=log,
        )
        return {**result, "launched": True}

    existing = find_run(root=root, key=key, config=config, run=run)
    if existing:
        summary = None
        try:
            summary = read_ticket(root=existing["path"], key=key, config=config)["title"]
        except (LaunchError, OSError, ValueError):
            pass
        return open_session(
            {
                "mode": "resume",
                "cwd": existing["path"],
                "args": ["--resume"],
                "summary": summary,
                "note": "run is done; resuming restarts the PR watch" if existing["stage"] == "done" else None,
                "worktree": existing,
                "selector": f"path:{existing['path']}",
            }
        )

    # With project rules, the session's `intake` step may write the ticket file, and it decides
    # title and base: start in the main checkout and let the session create the worktree.
    if config["orchestratorRules"] and not (Path(root) / config["ticketsDir"] / key / "ticket.md").exists():
        return open_session(
            {
                "mode": "main-checkout",
                "cwd": root,
                "args": [],
                "summary": None,
                "note": "no ticket.md yet; the session's intake rules write it",
            }
        )
    ticket = read_ticket(root=root, key=key, config=config)
    summary = ticket["title"]

    def main_checkout(note: str | None) -> dict:
        return open_session({"mode": "main-checkout", "cwd": root, "args": [], "summary": summary, "note": note})

    if host != "orca":
        return main_checkout(None)
    if not orca_has_repo(root=root, run=run):
        return main_checkout(f"{root} is not an Orca repo; the skill creates a git worktree")

    branch_base = resolve_base(root=root, ticket=ticket, config=config, run=run)
    if dry_run:
        argv = orca_worktree_args(root=root, key=key, title=ticket["title"], base=branch_base)
        planned = " ".join(a if _PLAIN_ARG.fullmatch(a) else shell_quote(a) for a in argv)
        return {
            **base,
            "mode": "orca-worktree",
            "base": branch_base,
            "cwd": f"<new Orca worktree {argv[argv.index('--name') + 1]}>",
            "title": session_name(key=key, summary=summary),
            "command": f"orca {planned}",
            "note": f"then /ticket {key} in the new worktree",
            "launched": False,
        }
    run("git", ["-C", root, "fetch", "origin", branch_base])
    # A failure from here on must not fall back to the main checkout: the session would create
    # a second worktree.
    worktree = create_orca_worktree(root=root, key=key, ticket=ticket, config=config, base=branch_base, run=run, log=log)
    opened = open_session(
        {
            "mode": "orca-worktree",
            "cwd": worktree["path"],
            "args": [],
            "summary": summary,
            "worktree": worktree,
            "selector": worktree["selector"],
        }
    )
    return {**opened, "base": branch_base}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

USAGE = """Usage: launch.mjs [--dry-run] [--remote-control] (KEY... | --all)

Opens one Claude Code session per ticket, running /ticket <KEY>, in a new
Orca or iTerm2 tab. A ticket with a run is resumed in its worktree.

  KEY...            tickets to open (<ticketsDir>/<KEY>/ticket.md)
  --all             every ticket file in the main checkout that has no run yet
  --dry-run         print what would be opened; run nothing
  --remote-control  also start each session with --remote-control
  --cwd DIR         a directory inside the repository (default: current)"""


def parse_args(argv: Sequence[str]) -> dict:
    opts: dict = {"keys": [], "all": False, "dryRun": False, "remoteControl": False, "cwd": None, "help": False}
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--all":
            opts["all"] = True
        elif a in ("--dry-run", "-n"):
            opts["dryRun"] = True
        elif a == "--remote-control":
            opts["remoteControl"] = True
        elif a in ("--help", "-h"):
            opts["help"] = True
        elif a == "--cwd":
            i += 1
            if i >= len(argv) or not argv[i]:
                raise LaunchError("--cwd needs a directory")
            opts["cwd"] = argv[i]
        elif a.startswith("-"):
            raise LaunchError(f"unknown option {a}")
        else:
            opts["keys"].append(a)
        i += 1
    if not opts["help"] and opts["all"] == bool(opts["keys"]):
        raise LaunchError("give ticket keys or --all (not both)")
    return opts


def describe(r: Mapping) -> str:
    lines = [f"{r['key']}: {r['mode']}{' (opened)' if r['launched'] else ''}"]
    if "host" in r:
        lines.append(f"  host:    {r['host'] or 'none (dry run only)'}")
    if r.get("base"):
        lines.append(f"  base:    {r['base']}")
    if r.get("cwd"):
        lines.append(f"  cwd:     {r['cwd']}")
    if r.get("title"):
        lines.append(f"  title:   {r['title']}")
    if r.get("command"):
        lines.append(f"  command: {r['command']}")
    if r.get("note"):
        lines.append(f"  note:    {r['note']}")
    return "\n".join(lines)


def _write(stream: Any) -> Callable[[str], None]:
    def write(line: str) -> None:
        stream.write(f"{line}\n")
        stream.flush()

    return write


def main(
    argv: Sequence[str] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    run: Run = default_run,
    out: Callable[[str], None] | None = None,
    err: Callable[[str], None] | None = None,
) -> int:
    """Runs the CLI; returns the exit code."""
    argv = sys.argv[1:] if argv is None else argv
    env = os.environ if env is None else env
    out = out or _write(sys.stdout)
    err = err or _write(sys.stderr)
    try:
        opts = parse_args(argv)
    except LaunchError as error:
        err(f"{error}\n\n{USAGE}")
        return 2
    if opts["help"]:
        out(USAGE)
        return 0
    try:
        root = find_root(cwd=opts["cwd"] or os.getcwd(), run=run)
        config = read_config(root=root)
    except (LaunchError, OSError) as error:
        err(str(error))
        return 1
    keys = opts["keys"]
    if opts["all"]:
        keys = []
        for key in list_ticket_keys(root=root, config=config):
            try:
                if not find_run(root=root, key=key, config=config, run=run):
                    keys.append(key)
            except LaunchError:
                pass
        if not keys:
            out(f"no ticket without a run in {config['ticketsDir']}")
            return 0
    failed = 0
    for key in keys:
        try:
            result = launch_ticket(
                root=root, key=key, config=config, remote_control=opts["remoteControl"], dry_run=opts["dryRun"], env=env, run=run, log=err
            )
            out(describe(result))
        except (LaunchError, OSError) as error:
            failed += 1
            err(f"{key}: {error}")
    return 1 if failed else 0
