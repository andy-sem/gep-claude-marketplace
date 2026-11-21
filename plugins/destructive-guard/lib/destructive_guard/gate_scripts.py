"""Script collection and scan for the approval gate (port of gate-scripts.mjs).

When a Bash command runs a project file (a shell script, a Node or Python file, a package
script, a GitHub workflow) this module finds the file, follows `source` and relative imports a
few levels deep, and reports the contents so the gate can
  - scan them for gated programs and cloud references (the fallback rules), and
  - hand them to Jev as context.
It names no concrete tool: programs come from the CLI rules, patterns and exempt globs from the
rules file. File access is read-only, bounded and symlink-aware.
"""

import contextlib
import json
import os
import re
import stat
from collections.abc import Mapping
from typing import Any

from .engine.normalizer import CommandNormalizer
from .rules.rule_loader import Rules
from .shell.cmd import Cmd as _Cmd
from .shell.tokenizer import ShellTokenizer
from .verdict import Verdict

__all__ = [
    "MAX_FILES",
    "MAX_FILE_BYTES",
    "MAX_FOLLOW_DEPTH",
    "collect_scripts",
    "find_project_root",
    "glob_to_regexp",
    "run_targets",
    "scan_scripts",
]

MAX_FILE_BYTES = 65536
MAX_FOLLOW_DEPTH = 3
MAX_FILES = 32

SHELLS = frozenset({"bash", "sh", "zsh"})
JS_EXT = re.compile(r"\.(?:[cm]?[jt]s|[jt]sx)\Z")
SHELL_EXT = re.compile(r"\.(?:sh|bash|zsh)\Z")
PYTHON_RE = re.compile(r"python(?:\d+(?:\.\d+)?)?", re.ASCII)
NODE_PRELOAD_OPTS = ["-r", "--require", "--import", "--loader"]
NODE_VALUE_OPTS = [*NODE_PRELOAD_OPTS, "-C", "--conditions", "--env-file", "--input-type"]
PKG_DIR_OPTS = ["-C", "--dir", "--prefix", "--cwd"]
NPM_LIFECYCLE = frozenset({"test", "start", "stop", "restart"})

_UNRESOLVABLE = re.compile(r"[$*?\[\x00]")
_YAML_EXT = re.compile(r"\.ya?ml\Z")
_DIGITS = re.compile(r"\d+", re.ASCII)

# ---------------------------------------------------------------------------
# Project root and paths
# ---------------------------------------------------------------------------


def _basename(path: str) -> str:
    return os.path.basename(path.rstrip("/")) if path.strip("/") else ""


def _join(base: str, rel: str) -> str:
    return os.path.normpath(f"{base}/{rel}")


def _resolve(base: str, rel: str) -> str:
    return os.path.abspath(os.path.join(base, rel))


def _at(items: list[str], index: int) -> str | None:
    return items[index] if 0 <= index < len(items) else None


def real_or_self(path: str) -> str:
    try:
        return os.path.realpath(path, strict=True)
    except (OSError, ValueError):
        return path


def find_project_root(cwd: str, env: Mapping[str, str] | None = None) -> str:
    """The nearest ancestor of `cwd` that has a `.git` entry (a directory, or the file a worktree
    has), else CLAUDE_PROJECT_DIR, else `cwd`. Always realpath'd."""
    if env is None:
        env = os.environ
    directory = os.path.abspath(cwd)
    while True:
        if os.path.exists(os.path.join(directory, ".git")):
            return real_or_self(directory)
        parent = os.path.dirname(directory)
        if parent == directory:
            break
        directory = parent
    return real_or_self(env.get("CLAUDE_PROJECT_DIR") or cwd)


def inside(root: str, real: str) -> bool:
    return real == root or real.startswith(root if root.endswith("/") else f"{root}/")


def rel_path(root: str, path: str) -> str:
    real = real_or_self(path)
    if inside(root, real):
        return real[len(root) + 1 :] or "."
    if inside(root, path):
        return path[len(root) + 1 :] or "."
    return path


def glob_to_regexp(glob: str) -> re.Pattern:
    """A small glob matcher for `**/`, `**`, `*` and `?`; every other character is literal. Anchored."""
    any_char = "[^\\n\\r\\u2028\\u2029]"
    out = ""
    i = 0
    n = len(glob)
    while i < n:
        c = glob[i]
        if c == "*" and i + 1 < n and glob[i + 1] == "*":
            if i + 2 < n and glob[i + 2] == "/":
                out += f"(?:{any_char}*/)?"
                i += 2
            else:
                out += f"{any_char}*"
                i += 1
        elif c == "*":
            out += "[^/]*"
        elif c == "?":
            out += "[^/]"
        else:
            out += re.escape(c)
        i += 1
    return re.compile(rf"\A{out}\Z")


def is_exempt_path(rel: str, rules: Rules) -> bool:
    return any(glob_to_regexp(g).search(rel) for g in rules.get("scriptScanExempt") or [])


# ---------------------------------------------------------------------------
# Which project files does a command run?
# ---------------------------------------------------------------------------


def unresolvable(token: str) -> bool:
    """A word that cannot be resolved to a path now: expansions, substitutions and globs."""
    return bool(_UNRESOLVABLE.search(token)) or token == "{}" or token.startswith("~")


def leading_options(tokens: list[str], value_opts: list[str]) -> dict[str, Any]:
    """Strips leading options. `value_opts` take a value (separate, attached to a short option or
    `--opt=value`)."""
    values: dict[str, str | None] = {}
    k = 0
    while k < len(tokens):
        t = tokens[k]
        if not t.startswith("-") or t == "-":
            break
        k += 1
        if t == "--":
            break
        eq = t.find("=")
        if t.startswith("--"):
            if eq != -1:
                values[t[:eq]] = t[eq + 1 :]
            elif t in value_opts:
                values[t] = _at(tokens, k)
                k += 1
        elif t in value_opts:
            values[t] = _at(tokens, k)
            k += 1
        elif len(t) > 2 and t[:2] in value_opts:
            values[t[:2]] = t[2:]
    return {"rest": tokens[k:], "values": values}


def node_operands(args: list[str]) -> dict[str, Any]:
    files: list[str | None] = []
    script: str | None = None
    test_mode = False
    i = 0
    n = len(args)
    while i < n:
        t = args[i]
        if t == "--":
            i += 1
            break
        if not t.startswith("-") or t == "-":
            break
        if t == "--test":
            test_mode = True
            i += 1
            continue
        if t == "--run" or t.startswith("--run="):
            if t == "--run":
                i += 1
                script = _at(args, i)
            else:
                script = t[6:]
            i += 1
            continue
        if t in ("--eval", "--print") or re.fullmatch(r"-[a-zA-Z]*[ep]", t):
            return {"files": files, "script": script, "eval": True}
        if t.startswith(("--eval=", "--print=")):
            return {"files": files, "script": script, "eval": True}
        eq = t.find("=")
        name = t if eq == -1 else t[:eq]
        if name in NODE_PRELOAD_OPTS:
            if eq == -1:
                i += 1
                files.append(_at(args, i))
            else:
                files.append(t[eq + 1 :])
        elif eq == -1 and name in NODE_VALUE_OPTS:
            i += 1
        elif re.match(r"-[rC].", t, re.DOTALL) and not t.startswith("--") and t[1] == "r":
            files.append(t[2:])
        i += 1
    if i < n:
        if test_mode:
            files.extend(args[i:])
        else:
            files.append(args[i])
    return {"files": files, "script": script}


def python_operand(args: list[str]) -> str | None:
    i = 0
    while i < len(args):
        t = args[i]
        if t == "-m" or t == "-c" or re.match(r"-[mc].", t, re.DOTALL):
            return None
        if t in ("-W", "-X"):
            i += 2
            continue
        if t == "-" or not t.startswith("-"):
            return None if t == "-" else t
        i += 1
    return None


def first_operand(args: list[str], value_opts: list[str] | None = None) -> str | None:
    return _at(leading_options(args, value_opts or [])["rest"], 0)


def read_scripts(pkg_file: str) -> dict | None:
    try:
        with open(pkg_file, encoding="utf-8", errors="replace") as f:
            parsed = json.loads(f.read())
    except (OSError, ValueError):
        return None
    scripts = parsed.get("scripts") if isinstance(parsed, dict) else None
    return scripts if isinstance(scripts, dict) else None


_WORKFLOW_NAME = re.compile(r"""^name:\s*["']?(.+?)["']?\s*$""", re.MULTILINE)


def workflow_name(file: str) -> str | None:
    """Top-level `name:` of a workflow file."""
    try:
        with open(file, encoding="utf-8", errors="replace") as f:
            m = _WORKFLOW_NAME.search(f.read())
    except OSError:
        return None
    return m.group(1) if m else None


def resolve_workflow(arg: str, root: str) -> dict | None:
    directory = _join(root, ".github/workflows")
    if _YAML_EXT.search(arg):
        return {"path": _join(directory, _basename(arg))}
    if _DIGITS.fullmatch(arg):
        return None
    try:
        names = [f for f in os.listdir(directory) if _YAML_EXT.search(f)]
    except OSError:
        return None
    for f in sorted(names):
        if workflow_name(_join(directory, f)) == arg:
            return {"path": _join(directory, f)}
    return None


# `terraform test` (or `tofu test`, also as a container entrypoint such as `docker run -w <dir>
# --entrypoint terraform <image> test`) runs the `*.tftest.hcl` files of the root module and of its
# test directory. They decide whether the run touches the cloud (`mock_provider`, `command =
# plan|apply`), so they go to Jev as `{path, cwd, context: True}` targets. Context files are exempt
# from the script scan: the terraform rule already judges the command. [] when the directory is dynamic.
TF_PROGRAMS = frozenset({"terraform", "tofu"})
WORKDIR_OPTS = ["-w", "--workdir"]
CONTAINERS = frozenset({"docker", "podman"})


def option_value(tokens: list[str], names: list[str]) -> str | None:
    for i, token in enumerate(tokens):
        for n in names:
            if token == n:
                return _at(tokens, i + 1) or ""
            if token.startswith(f"{n}="):
                return token[len(n) + 1 :]
    return None


def terraform_test_targets(tokens: list[str], cwd: str | None) -> list[dict]:
    idx = next((i for i, t in enumerate(tokens) if _basename(t) in TF_PROGRAMS), -1)
    if idx < 0:
        return []
    rest = tokens[idx + 1 :]
    if "test" not in [t for t in rest if not t.startswith("-")]:
        return []
    directory = cwd
    if idx > 0:
        # only a local container sees the same files; `ssh host terraform test` does not
        if _basename(tokens[0]) not in CONTAINERS or _at(tokens, 1) != "run":
            return []
        # without -w the container starts in the image's directory, not ours
        workdir = option_value(tokens[:idx], WORKDIR_OPTS)
        if not workdir or unresolvable(workdir) or not os.path.isabs(workdir):
            return []
        directory = workdir
    chdir = option_value(rest, ["-chdir"])
    if chdir is not None:
        if unresolvable(chdir) or not directory:
            return []
        directory = _resolve(directory, chdir)
    test_dir = option_value(rest, ["-test-directory"])
    if test_dir is None:
        test_dir = "tests"
    if not directory or unresolvable(test_dir):
        return []
    out = []
    for d in (directory, _resolve(directory, test_dir)):
        try:
            names = sorted(os.listdir(d))
        except OSError:
            continue
        for name in names:
            if name.endswith(".tftest.hcl"):
                out.append({"path": _join(d, name), "cwd": directory, "context": True})
    return out


def run_targets(raw_tokens: list[str], rules: Rules, *, cwd: str | None, root: str, depth: int = 0) -> list[dict]:
    """The project files one simple command runs: `{path, cwd}` for a file, `{path, script}` for a
    package script (`path` is its package.json). Paths are absolute, resolved against `cwd`; `cwd` is
    None once a `cd` target was dynamic. A file's `cwd` is the directory the command ran in, which a
    `source ./x` inside it is relative to."""
    if depth > 4:
        return []
    try:
        stripped = CommandNormalizer(rules).strip_wrappers(raw_tokens)["tokens"]
    except Exception:  # noqa: BLE001 (any parse failure: no targets)
        return []
    if not stripped:
        return []
    word = stripped[0]
    base = _basename(word)
    args = stripped[1:]
    out: list[dict] = []
    # A shell command string handed over by a wrapper or runner (`watch bash x.sh`, `npx -c '…'`);
    # a plain `bash -c '…'` is already split out by split_command.
    first = next((t for t in raw_tokens if not ShellTokenizer.ASSIGNMENT_RE.match(t)), None)
    if first is not None and _basename(first) not in SHELLS:
        nested = CommandNormalizer(rules).nested_shell_string(raw_tokens)
        if nested is not None:
            out.extend(command_targets(nested, rules, cwd, root, depth + 1))

    def file(arg: str | None, frm: str | None = cwd) -> None:
        if not isinstance(arg, str) or arg == "" or unresolvable(arg):
            return
        if os.path.isabs(arg):
            out.append({"path": arg, "cwd": cwd})
        elif frm:
            out.append({"path": _resolve(frm, arg), "cwd": frm})

    out.extend(terraform_test_targets(stripped, cwd))

    if word in ("source", "."):
        file(_at(args, 0))
        return out
    bare_or_abs = "/" not in word or os.path.isabs(word)
    if base in SHELLS and bare_or_abs:
        idx = CommandNormalizer.shell_script_index(stripped)
        if idx > 0:
            file(stripped[idx])
        return out
    if base == "node" and bare_or_abs:
        info = node_operands(args)
        for f in info["files"]:
            file(f)
        if info.get("script") and cwd:
            out.append({"path": _join(cwd, "package.json"), "script": info["script"]})
        return out
    if PYTHON_RE.fullmatch(base) and bare_or_abs:
        file(python_operand(args))
        return out
    if base == "tsx" and "/" not in word:
        rest = leading_options(args, ["--tsconfig", "-r", "--import"])["rest"]
        file(_at(rest, 1) if _at(rest, 0) == "watch" else _at(rest, 0))
        return out
    if base == "deno" and "/" not in word:
        rest = leading_options(args, [])["rest"]
        if _at(rest, 0) == "run":
            file(_at(leading_options(rest[1:], [])["rest"], 0))
        return out
    if base == "gh" and _at(args, 0) == "workflow" and _at(args, 1) == "run":
        operand = first_operand(args[2:], ["-r", "--ref", "-f", "--raw-field", "-F", "--field", "-R", "--repo"])
        if operand and not unresolvable(operand):
            wf = resolve_workflow(operand, root)
            if wf:
                out.append(wf)
        return out

    runner = next((r for r in rules["runners"] if r["program"] == base), None)
    if runner and base in ("pnpm", "npm", "yarn", "bun"):
        opts = leading_options(args, runner["valueOptions"])
        rest, values = opts["rest"], opts["values"]
        dir_opt = next((v for v in (values.get(o) for o in PKG_DIR_OPTS) if v), None)
        if dir_opt is not None and unresolvable(dir_opt):
            return out
        pkg_dir = _resolve(cwd if cwd is not None else root, dir_opt) if dir_opt else cwd
        pkg_file = _join(pkg_dir, "package.json") if pkg_dir else None

        def script(name: str | None) -> None:
            if pkg_file and name and not unresolvable(name):
                out.append({"path": pkg_file, "script": name})

        head = _at(rest, 0)
        if head in ("run", "run-script"):
            after = leading_options(rest[1:], runner["valueOptions"])
            script(_at(after["rest"], 0))
            return out
        if base == "npm" and head in NPM_LIFECYCLE:
            script(head)
            return out
        if base != "npm" and head and pkg_file:
            scripts = read_scripts(pkg_file)
            if scripts is not None and head in scripts:
                script(head)
                return out
        # A runner that runs another program: `pnpm exec node x.mjs`, `npx tsx x.ts`.
        nxt = rest
        if nxt and nxt[0] in runner["subcommands"]:
            nxt = leading_options(nxt[1:], runner["valueOptions"])["rest"]
        elif not runner["bareBin"]:
            return out
        if nxt:
            out.extend(run_targets(nxt, rules, cwd=pkg_dir if pkg_dir is not None else cwd, root=root, depth=depth + 1))
        return out
    if runner and runner["bareBin"]:
        nxt = leading_options(args, runner["valueOptions"])["rest"]
        if nxt:
            out.extend(run_targets(nxt, rules, cwd=cwd, root=root, depth=depth + 1))
        return out
    # `./x.sh`, `infra/cloud/apply.sh`; an absolute path outside the project is a system program,
    # not a script
    if "/" in word and not word.startswith("-"):
        system_program = os.path.isabs(word) and not inside(root, real_or_self(word)) and not inside(root, word)
        if not system_program:
            file(word)
    return out


_VAR_REF = re.compile(r"\$(?:\{([A-Za-z_]\w*)\}|([A-Za-z_]\w*))", re.ASCII)


def expand_vars(token: str, variables: dict[str, str]) -> str:
    if not variables or "$" not in token:
        return token

    def repl(m: re.Match) -> str:
        value = variables.get(m.group(1) if m.group(1) is not None else m.group(2))
        return m.group(0) if value is None else value

    return _VAR_REF.sub(repl, token)


def _copy_state(s: dict) -> dict:
    return {"here": s["here"], "stack": list(s["stack"]), "vars": dict(s["vars"])}


def command_targets(command: str, rules: Rules, cwd: str | None, root: str, depth: int = 0) -> list[dict]:
    """Targets of a whole command string. A literal `cd <dir>` or `pushd <dir>` moves the directory
    for the commands after it in the same scope, `popd` goes back; after a dynamic or missing target
    relative files are dropped. A `cd` inside a `( … )` group or a substitution does not move the
    directory of the commands after the group. Commands of a string a shell was given with `-c` start
    in the directory the shell command itself ran in (`scope.host`), not the one the main command
    ended in.

    Variables assigned earlier in the same command (`P=$D/infra; cd $P`) are expanded; anything else
    stays a `$` word, which is unresolvable."""
    try:
        simple = ShellTokenizer.split_command(command)
    except Exception:  # noqa: BLE001 (unparsable: the rule layer asks)
        return []
    out: list[dict] = []
    states: dict[Any, dict] = {}  # per scope: the directory and the pushd stack
    snapshots: dict[int, dict] = {}  # per command (by identity): the state it ran in, for the strings it hosts
    main_root: list[Any] = []

    def state_of(scope: Any) -> dict:
        state = states.get(scope)
        if state is not None:
            return state
        if scope.parent:
            state = _copy_state(state_of(scope.parent))
        elif scope.host is not None and id(scope.host) in snapshots:
            state = _copy_state(snapshots[id(scope.host)])
        elif not main_root:
            main_root.append(scope)
            state = {"here": cwd, "stack": [], "vars": {}}
        else:
            state = _copy_state(states[main_root[0]])
        states[scope] = state
        return state

    for raw in simple:
        state = state_of(raw.scope) if raw.scope else {"here": cwd, "stack": [], "vars": {}}
        snapshots[id(raw)] = _copy_state(state)
        tokens = _Cmd([expand_vars(t, state["vars"]) for t in raw], stdin=raw.stdin, scope=raw.scope)
        # `D=/abs; P=$D/x`: a command of assignments only sets variables for the commands after it;
        # `X=1 cmd` sets X for cmd alone
        if tokens and all(ShellTokenizer.ASSIGNMENT_RE.match(t) for t in tokens):
            for t in tokens:
                eq = t.index("=")
                state["vars"][t[:eq]] = t[eq + 1 :]
            continue
        stripped: list[str] = tokens
        with contextlib.suppress(Exception):
            stripped = CommandNormalizer(rules).strip_wrappers(tokens)["tokens"]
        word = stripped[0] if stripped else None
        if word in ("cd", "pushd"):
            target = next((t for t in stripped[1:] if not t.startswith("-")), None)
            if word == "pushd":
                state["stack"].append(state["here"])
            state["here"] = (
                _resolve(state["here"], target)
                if state["here"] and target and not unresolvable(target) and target != "-"
                else None
            )
            continue
        if word == "popd":
            state["here"] = state["stack"].pop() if state["stack"] else None
            continue
        out.extend(run_targets(tokens, rules, cwd=state["here"], root=root, depth=depth))
    return out


# ---------------------------------------------------------------------------
# Following source and imports
# ---------------------------------------------------------------------------

_SCRIPT_DIR_RES = [
    re.compile(r"""\"?\$\(\s*dirname\s+\"?\$\{?(?:0|BASH_SOURCE(?:\[0\])?)\}?\"?\s*\)\"?""", re.ASCII),
    re.compile(r"\$\{(?:BASH_SOURCE(?:\[0\])?|0)%/\*\}", re.ASCII),
    re.compile(r"\$\{?(?:SCRIPT_DIR|SCRIPTDIR|HERE|DIR)\}?", re.ASCII),
]
_ROOT_DIR_RE = re.compile(r"\$\{?(?:REPO_ROOT|ROOT_DIR|PROJECT_ROOT)\}?", re.ASCII)
_SOURCE_RE = re.compile(r"(?:^|[;&|({]|\bthen\b|\bdo\b|\belse\b)[ \t]*(?:source|\.)[ \t]+([^\n]+)", re.MULTILINE | re.ASCII)
_ARG_END = re.compile(r"[\s;&|)]")


def source_targets(content: str, script_dir: str, cwd: str | None, root: str) -> list[dict]:
    out = []
    for m in _SOURCE_RE.finditer(content):
        arg = m.group(1)
        for sd in _SCRIPT_DIR_RES:
            arg = sd.sub("\u0001", arg)
        arg = _ROOT_DIR_RE.sub("\u0002", arg)
        arg = arg.replace('"', "").replace("'", "")
        arg = _ARG_END.split(arg)[0]
        if not arg or unresolvable(arg.replace("\u0001", "").replace("\u0002", "")):
            continue
        if arg.startswith("\u0001"):
            arg = _join(script_dir, arg[1:])
        elif arg.startswith("\u0002"):
            arg = _join(root, arg[1:])
        elif not os.path.isabs(arg):
            if not cwd:
                continue
            arg = _resolve(cwd, arg)
        if "\u0001" not in arg and "\u0002" not in arg:
            out.append({"path": arg})
    return out


_IMPORT_RES = [
    re.compile(r"""\b(?:import|export)\b[^'"`;]*?\bfrom\s*(['"])([^'"\n]+)\1""", re.ASCII),
    re.compile(r"""\bimport\s*(['"])([^'"\n]+)\1""", re.ASCII),
    re.compile(r"""\b(?:import|require)\s*\(\s*(['"])([^'"\n]+)\1\s*\)""", re.ASCII),
]
_TRY_EXT = [".js", ".mjs", ".cjs", ".ts", ".mts", ".cts", ".tsx", ".jsx"]
_EXT_SWAP = {".js": ".ts", ".mjs": ".mts", ".cjs": ".cts", ".jsx": ".tsx"}


def is_file(path: str) -> bool:
    try:
        return stat.S_ISREG(os.stat(path).st_mode)
    except (OSError, ValueError):
        return False


def resolve_import(directory: str, spec: str) -> str:
    base = _resolve(directory, spec)
    candidates = [base]
    ext = os.path.splitext(base)[1]
    if ext in _EXT_SWAP:
        candidates.append(base[: -len(ext)] + _EXT_SWAP[ext])
    candidates.extend(base + e for e in _TRY_EXT)
    candidates.extend(_join(base, f"index{e}") for e in _TRY_EXT)
    return next((c for c in candidates if is_file(c)), base)


def import_targets(content: str, directory: str) -> list[dict]:
    found = []
    for rx in _IMPORT_RES:
        for m in rx.finditer(content):
            spec = m.group(2)
            if spec.startswith(("./", "../")):
                found.append((m.start(), spec))
    found.sort(key=lambda f: f[0])  # source order, whichever pattern matched
    return [{"path": resolve_import(directory, spec)} for _, spec in found]


_SHEBANG = re.compile(r"#!\s*(\S+)(?:\s+(\S+))?")
_JS_PROGRAMS = frozenset({"node", "tsx", "deno", "bun"})


def kind_of(path: str, content: str) -> str:
    if JS_EXT.search(path):
        return "js"
    if SHELL_EXT.search(path):
        return "shell"
    shebang = _SHEBANG.match(content)
    if shebang:
        first = shebang.group(1)
        prog = _basename(shebang.group(2) or "" if _basename(first) == "env" else first)
        if prog in SHELLS:
            return "shell"
        if prog in _JS_PROGRAMS:
            return "js"
        return "other"
    return "shell" if os.path.splitext(path)[1] == "" else "other"


def read_head(real: str, size: int) -> str:
    with open(real, "rb") as f:
        data = f.read(min(size, MAX_FILE_BYTES))
    return data.decode("utf-8", errors="replace")


def collect_scripts(command: str, rules: Rules, *, cwd: str, root: str) -> dict[str, Any]:
    """Reads the files `command` runs and the files they pull in (breadth-first, in source order).
    Returns `{"files", "problems"}`:
    - files: `{path, content, size, truncated, exempt, depth}`, `path` relative to the project root
      (a package script is `<dir>/package.json#scripts.<name>`);
    - problems: `{path, reason, exempt}` for files the gate could not read safely.
    A missing file is skipped. An unparsable command gives nothing: the rule layer already asks."""
    files: list[dict] = []
    problems: list[dict] = []
    seen: set[str] = set()

    def queue_item(t: dict, depth: int, parent_exempt: bool, frm: str | None) -> dict:
        # the directory a target's own command ran in, else the one of the file it came from
        return {**t, "depth": depth, "parentExempt": parent_exempt, "cwd": t.get("cwd", frm)}

    queue = [queue_item(t, 0, False, cwd) for t in command_targets(command, rules, cwd, root)]
    capped = False
    qi = 0
    while qi < len(queue):
        item = queue[qi]
        qi += 1
        try:
            real = os.path.realpath(item["path"], strict=True)
        except (FileNotFoundError, NotADirectoryError):
            continue
        except (OSError, ValueError):
            problems.append({"path": rel_path(root, item["path"]), "reason": "is unreadable", "exempt": item["parentExempt"]})
            continue
        script = item.get("script")
        key = f"{real}#{script}" if script else real
        if key in seen:
            continue
        seen.add(key)
        shown = f"{rel_path(root, item['path'])}#scripts.{script}" if script else rel_path(root, item["path"])
        exempt = item["parentExempt"] or item.get("context") is True or is_exempt_path(shown.split("#")[0], rules)

        def problem(reason: str, shown: str = shown, exempt: bool = exempt) -> None:
            problems.append({"path": shown, "reason": reason, "exempt": exempt})

        if not inside(root, real):
            problem("is outside the project")
            continue
        try:
            st = os.stat(real)
        except OSError:
            problem("is unreadable")
            continue
        if not stat.S_ISREG(st.st_mode):
            problem("is not a regular file")
            continue
        if len(files) >= MAX_FILES:
            if not capped:
                problems.append({"path": shown, "reason": f"more than {MAX_FILES} files", "exempt": False})
            capped = True
            break
        size = st.st_size
        truncated = False
        try:
            content = read_head(real, st.st_size)
        except OSError:
            problem("is unreadable")
            continue
        if script:
            try:
                with open(real, encoding="utf-8", errors="replace") as f:
                    parsed = json.loads(f.read())
            except (OSError, ValueError):
                problem("is unreadable")
                continue
            scripts = parsed.get("scripts") if isinstance(parsed, dict) else None
            body = scripts.get(script) if isinstance(scripts, dict) else None
            if not isinstance(body, str):
                continue
            content = body
            size = len(body.encode("utf-8"))
        if size > MAX_FILE_BYTES:
            truncated = True
            content = content[:MAX_FILE_BYTES]
            problem("exceeds 64 KB")
        files.append(
            {"path": shown, "content": content, "size": size, "truncated": truncated, "exempt": exempt, "depth": item["depth"]}
        )

        if item["depth"] >= MAX_FOLLOW_DEPTH:
            continue
        directory = os.path.dirname(real)
        nxt: list[dict] = []
        if script:
            nxt = command_targets(content, rules, directory, root)
        else:
            kind = kind_of(real, content)
            if kind == "shell":
                nxt = source_targets(content, directory, item["cwd"], root)
            elif kind == "js":
                nxt = import_targets(content, directory)
        for t in nxt:
            queue.append(queue_item(t, item["depth"] + 1, exempt, item["cwd"]))
    return {"files": files, "problems": problems}


# ---------------------------------------------------------------------------
# Scan
# ---------------------------------------------------------------------------


def escape_re(s: str) -> str:
    return re.escape(s)


def program_names(rules: Rules) -> list[str]:
    """The program names a script could run: those named by the CLI rules and by an mcp-as-cli rule
    (the rules file is the only place that names tools)."""
    names: dict[str, None] = {}
    for rule in rules["rules"]:
        kind = rule["kind"]
        if kind in ("cli-allowlist", "cli-gated"):
            if rule.get("scriptScan") is False:
                continue
            for p in rule["programs"]:
                names[p] = None
        elif kind == "mcp-as-cli":
            names[rule["program"]] = None
    return list(names)


def scan_scripts(collected: dict | None, rules: Rules) -> dict | None:
    """Looks at the non-exempt files and problems: an unreadable, outside-project or oversized file
    asks, then a program name, then a `scriptPatterns` match. Returns an `ask` result or None."""
    if not collected:
        return None
    patterns = rules.get("scriptPatterns") or []
    programs = program_names(rules)
    # Nothing to look for: no program names and no patterns.
    if not programs and not patterns:
        return None
    problem = next((p for p in collected["problems"] if not p["exempt"]), None)
    if problem:
        return Verdict.ask("script", f"{problem['path']} {problem['reason']}")
    scanned = [f for f in collected["files"] if not f["exempt"]]
    names = [(name, re.compile(rf"(?<![\w.@-]){escape_re(name)}(?![\w-])", re.ASCII)) for name in programs]
    for f in scanned:
        for name, rx in names:
            if rx.search(f["content"]):
                return Verdict.ask("script", f"{f['path']} runs {name}")
    for f in scanned:
        for rx in patterns:
            if rx.search(f["content"]):
                return Verdict.ask("script", f"{f['path']} references {rx.pattern}")
    return None
