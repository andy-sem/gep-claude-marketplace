"""Which project files does a command run?"""

import contextlib
import json
import os
import re
from typing import Any, ClassVar

from ..engine.normalizer import CommandNormalizer
from ..rules.rule_loader import Rules
from ..shell.cmd import Cmd as _Cmd
from ..shell.tokenizer import ShellTokenizer
from .project_paths import ProjectPaths


class RunTargetResolver:
    """Finds the project files a command runs, relative to `cwd` inside the project `root`."""

    SHELLS = frozenset({"bash", "sh", "zsh"})
    PYTHON_RE = re.compile(r"python(?:\d+(?:\.\d+)?)?", re.ASCII)
    NODE_PRELOAD_OPTS: ClassVar[list[str]] = ["-r", "--require", "--import", "--loader"]
    NODE_VALUE_OPTS: ClassVar[list[str]] = [*NODE_PRELOAD_OPTS, "-C", "--conditions", "--env-file", "--input-type"]
    PKG_DIR_OPTS: ClassVar[list[str]] = ["-C", "--dir", "--prefix", "--cwd"]
    NPM_LIFECYCLE = frozenset({"test", "start", "stop", "restart"})

    _UNRESOLVABLE = re.compile(r"[$*?\[\x00]")
    _YAML_EXT = re.compile(r"\.ya?ml\Z")
    _DIGITS = re.compile(r"\d+", re.ASCII)
    _WORKFLOW_NAME = re.compile(r"""^name:\s*["']?(.+?)["']?\s*$""", re.MULTILINE)
    _VAR_REF = re.compile(r"\$(?:\{([A-Za-z_]\w*)\}|([A-Za-z_]\w*))", re.ASCII)

    # `terraform test` (or `tofu test`, also as a container entrypoint such as `docker run -w <dir>
    # --entrypoint terraform <image> test`) runs the `*.tftest.hcl` files of the root module and of its
    # test directory. They decide whether the run touches the cloud (`mock_provider`, `command =
    # plan|apply`), so they go to Jev as `{path, cwd, context: True}` targets. Context files are exempt
    # from the script scan: the terraform rule already judges the command. [] when the directory is dynamic.
    TF_PROGRAMS = frozenset({"terraform", "tofu"})
    WORKDIR_OPTS: ClassVar[list[str]] = ["-w", "--workdir"]
    CONTAINERS = frozenset({"docker", "podman"})

    def __init__(self, rules: Rules, cwd: str | None, root: str) -> None:
        self.rules = rules
        self.cwd = cwd
        self.root = root

    @classmethod
    def unresolvable(cls, token: str) -> bool:
        """A word that cannot be resolved to a path now: expansions, substitutions and globs."""
        return bool(cls._UNRESOLVABLE.search(token)) or token == "{}" or token.startswith("~")

    @staticmethod
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
                    values[t] = ProjectPaths._at(tokens, k)
                    k += 1
            elif t in value_opts:
                values[t] = ProjectPaths._at(tokens, k)
                k += 1
            elif len(t) > 2 and t[:2] in value_opts:
                values[t[:2]] = t[2:]
        return {"rest": tokens[k:], "values": values}

    @classmethod
    def node_operands(cls, args: list[str]) -> dict[str, Any]:
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
                    script = ProjectPaths._at(args, i)
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
            if name in cls.NODE_PRELOAD_OPTS:
                if eq == -1:
                    i += 1
                    files.append(ProjectPaths._at(args, i))
                else:
                    files.append(t[eq + 1 :])
            elif eq == -1 and name in cls.NODE_VALUE_OPTS:
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

    @staticmethod
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

    @classmethod
    def first_operand(cls, args: list[str], value_opts: list[str] | None = None) -> str | None:
        return ProjectPaths._at(cls.leading_options(args, value_opts or [])["rest"], 0)

    @staticmethod
    def read_scripts(pkg_file: str) -> dict | None:
        try:
            with open(pkg_file, encoding="utf-8", errors="replace") as f:
                parsed = json.loads(f.read())
        except (OSError, ValueError):
            return None
        scripts = parsed.get("scripts") if isinstance(parsed, dict) else None
        return scripts if isinstance(scripts, dict) else None

    @classmethod
    def workflow_name(cls, file: str) -> str | None:
        """Top-level `name:` of a workflow file."""
        try:
            with open(file, encoding="utf-8", errors="replace") as f:
                m = cls._WORKFLOW_NAME.search(f.read())
        except OSError:
            return None
        return m.group(1) if m else None

    def resolve_workflow(self, arg: str) -> dict | None:
        directory = ProjectPaths._join(self.root, ".github/workflows")
        if self._YAML_EXT.search(arg):
            return {"path": ProjectPaths._join(directory, ProjectPaths._basename(arg))}
        if self._DIGITS.fullmatch(arg):
            return None
        try:
            names = [f for f in os.listdir(directory) if self._YAML_EXT.search(f)]
        except OSError:
            return None
        for f in sorted(names):
            if self.workflow_name(ProjectPaths._join(directory, f)) == arg:
                return {"path": ProjectPaths._join(directory, f)}
        return None

    @staticmethod
    def option_value(tokens: list[str], names: list[str]) -> str | None:
        for i, token in enumerate(tokens):
            for n in names:
                if token == n:
                    return ProjectPaths._at(tokens, i + 1) or ""
                if token.startswith(f"{n}="):
                    return token[len(n) + 1 :]
        return None

    def terraform_test_targets(self, tokens: list[str]) -> list[dict]:
        idx = next((i for i, t in enumerate(tokens) if ProjectPaths._basename(t) in self.TF_PROGRAMS), -1)
        if idx < 0:
            return []
        rest = tokens[idx + 1 :]
        if "test" not in [t for t in rest if not t.startswith("-")]:
            return []
        directory = self.cwd
        if idx > 0:
            # only a local container sees the same files; `ssh host terraform test` does not
            if ProjectPaths._basename(tokens[0]) not in self.CONTAINERS or ProjectPaths._at(tokens, 1) != "run":
                return []
            # without -w the container starts in the image's directory, not ours
            workdir = self.option_value(tokens[:idx], self.WORKDIR_OPTS)
            if not workdir or self.unresolvable(workdir) or not os.path.isabs(workdir):
                return []
            directory = workdir
        chdir = self.option_value(rest, ["-chdir"])
        if chdir is not None:
            if self.unresolvable(chdir) or not directory:
                return []
            directory = ProjectPaths._resolve(directory, chdir)
        test_dir = self.option_value(rest, ["-test-directory"])
        if test_dir is None:
            test_dir = "tests"
        if not directory or self.unresolvable(test_dir):
            return []
        out = []
        for d in (directory, ProjectPaths._resolve(directory, test_dir)):
            try:
                names = sorted(os.listdir(d))
            except OSError:
                continue
            for name in names:
                if name.endswith(".tftest.hcl"):
                    out.append({"path": ProjectPaths._join(d, name), "cwd": directory, "context": True})
        return out

    def run_targets(self, raw_tokens: list[str], depth: int = 0) -> list[dict]:
        """The project files one simple command runs: `{path, cwd}` for a file, `{path, script}` for a
        package script (`path` is its package.json). Paths are absolute, resolved against `cwd`; `cwd` is
        None once a `cd` target was dynamic. A file's `cwd` is the directory the command ran in, which a
        `source ./x` inside it is relative to."""
        if depth > 4:
            return []
        try:
            stripped = CommandNormalizer(self.rules).strip_wrappers(raw_tokens)["tokens"]
        except Exception:  # noqa: BLE001 (any parse failure: no targets)
            return []
        if not stripped:
            return []
        word = stripped[0]
        base = ProjectPaths._basename(word)
        args = stripped[1:]
        out: list[dict] = []
        # A shell command string handed over by a wrapper or runner (`watch bash x.sh`, `npx -c '…'`);
        # a plain `bash -c '…'` is already split out by split_command.
        first = next((t for t in raw_tokens if not ShellTokenizer.ASSIGNMENT_RE.match(t)), None)
        if first is not None and ProjectPaths._basename(first) not in self.SHELLS:
            nested = CommandNormalizer(self.rules).nested_shell_string(raw_tokens)
            if nested is not None:
                out.extend(self.command_targets(nested, depth + 1))

        def file(arg: str | None, frm: str | None = self.cwd) -> None:
            if not isinstance(arg, str) or arg == "" or self.unresolvable(arg):
                return
            if os.path.isabs(arg):
                out.append({"path": arg, "cwd": self.cwd})
            elif frm:
                out.append({"path": ProjectPaths._resolve(frm, arg), "cwd": frm})

        out.extend(self.terraform_test_targets(stripped))

        if word in ("source", "."):
            file(ProjectPaths._at(args, 0))
            return out
        bare_or_abs = "/" not in word or os.path.isabs(word)
        if base in self.SHELLS and bare_or_abs:
            idx = CommandNormalizer.shell_script_index(stripped)
            if idx > 0:
                file(stripped[idx])
            return out
        if base == "node" and bare_or_abs:
            info = self.node_operands(args)
            for f in info["files"]:
                file(f)
            if info.get("script") and self.cwd:
                out.append({"path": ProjectPaths._join(self.cwd, "package.json"), "script": info["script"]})
            return out
        if self.PYTHON_RE.fullmatch(base) and bare_or_abs:
            file(self.python_operand(args))
            return out
        if base == "tsx" and "/" not in word:
            rest = self.leading_options(args, ["--tsconfig", "-r", "--import"])["rest"]
            file(ProjectPaths._at(rest, 1) if ProjectPaths._at(rest, 0) == "watch" else ProjectPaths._at(rest, 0))
            return out
        if base == "deno" and "/" not in word:
            rest = self.leading_options(args, [])["rest"]
            if ProjectPaths._at(rest, 0) == "run":
                file(ProjectPaths._at(self.leading_options(rest[1:], [])["rest"], 0))
            return out
        if base == "gh" and ProjectPaths._at(args, 0) == "workflow" and ProjectPaths._at(args, 1) == "run":
            operand = self.first_operand(args[2:], ["-r", "--ref", "-f", "--raw-field", "-F", "--field", "-R", "--repo"])
            if operand and not self.unresolvable(operand):
                wf = self.resolve_workflow(operand)
                if wf:
                    out.append(wf)
            return out

        runner = next((r for r in self.rules["runners"] if r["program"] == base), None)
        if runner and base in ("pnpm", "npm", "yarn", "bun"):
            opts = self.leading_options(args, runner["valueOptions"])
            rest, values = opts["rest"], opts["values"]
            dir_opt = next((v for v in (values.get(o) for o in self.PKG_DIR_OPTS) if v), None)
            if dir_opt is not None and self.unresolvable(dir_opt):
                return out
            pkg_dir = ProjectPaths._resolve(self.cwd if self.cwd is not None else self.root, dir_opt) if dir_opt else self.cwd
            pkg_file = ProjectPaths._join(pkg_dir, "package.json") if pkg_dir else None

            def script(name: str | None) -> None:
                if pkg_file and name and not self.unresolvable(name):
                    out.append({"path": pkg_file, "script": name})

            head = ProjectPaths._at(rest, 0)
            if head in ("run", "run-script"):
                after = self.leading_options(rest[1:], runner["valueOptions"])
                script(ProjectPaths._at(after["rest"], 0))
                return out
            if base == "npm" and head in self.NPM_LIFECYCLE:
                script(head)
                return out
            if base != "npm" and head and pkg_file:
                scripts = self.read_scripts(pkg_file)
                if scripts is not None and head in scripts:
                    script(head)
                    return out
            # A runner that runs another program: `pnpm exec node x.mjs`, `npx tsx x.ts`.
            nxt = rest
            if nxt and nxt[0] in runner["subcommands"]:
                nxt = self.leading_options(nxt[1:], runner["valueOptions"])["rest"]
            elif not runner["bareBin"]:
                return out
            if nxt:
                out.extend(
                    RunTargetResolver(self.rules, pkg_dir if pkg_dir is not None else self.cwd, self.root).run_targets(
                        nxt, depth=depth + 1
                    )
                )
            return out
        if runner and runner["bareBin"]:
            nxt = self.leading_options(args, runner["valueOptions"])["rest"]
            if nxt:
                out.extend(self.run_targets(nxt, depth=depth + 1))
            return out
        # `./x.sh`, `infra/cloud/apply.sh`; an absolute path outside the project is a system program,
        # not a script
        if "/" in word and not word.startswith("-"):
            system_program = os.path.isabs(word) and not ProjectPaths.inside(self.root, ProjectPaths.real_or_self(word)) and not ProjectPaths.inside(self.root, word)
            if not system_program:
                file(word)
        return out

    @classmethod
    def expand_vars(cls, token: str, variables: dict[str, str]) -> str:
        if not variables or "$" not in token:
            return token

        def repl(m: re.Match) -> str:
            value = variables.get(m.group(1) if m.group(1) is not None else m.group(2))
            return m.group(0) if value is None else value

        return cls._VAR_REF.sub(repl, token)

    @staticmethod
    def _copy_state(s: dict) -> dict:
        return {"here": s["here"], "stack": list(s["stack"]), "vars": dict(s["vars"])}

    def command_targets(self, command: str, depth: int = 0) -> list[dict]:
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
                state = self._copy_state(state_of(scope.parent))
            elif scope.host is not None and id(scope.host) in snapshots:
                state = self._copy_state(snapshots[id(scope.host)])
            elif not main_root:
                main_root.append(scope)
                state = {"here": self.cwd, "stack": [], "vars": {}}
            else:
                state = self._copy_state(states[main_root[0]])
            states[scope] = state
            return state

        for raw in simple:
            state = state_of(raw.scope) if raw.scope else {"here": self.cwd, "stack": [], "vars": {}}
            snapshots[id(raw)] = self._copy_state(state)
            tokens = _Cmd([self.expand_vars(t, state["vars"]) for t in raw], stdin=raw.stdin, scope=raw.scope)
            # `D=/abs; P=$D/x`: a command of assignments only sets variables for the commands after it;
            # `X=1 cmd` sets X for cmd alone
            if tokens and all(ShellTokenizer.ASSIGNMENT_RE.match(t) for t in tokens):
                for t in tokens:
                    eq = t.index("=")
                    state["vars"][t[:eq]] = t[eq + 1 :]
                continue
            stripped: list[str] = tokens
            with contextlib.suppress(Exception):
                stripped = CommandNormalizer(self.rules).strip_wrappers(tokens)["tokens"]
            word = stripped[0] if stripped else None
            if word in ("cd", "pushd"):
                target = next((t for t in stripped[1:] if not t.startswith("-")), None)
                if word == "pushd":
                    state["stack"].append(state["here"])
                state["here"] = (
                    ProjectPaths._resolve(state["here"], target)
                    if state["here"] and target and not self.unresolvable(target) and target != "-"
                    else None
                )
                continue
            if word == "popd":
                state["here"] = state["stack"].pop() if state["stack"] else None
                continue
            out.extend(RunTargetResolver(self.rules, state["here"], self.root).run_targets(tokens, depth=depth))
        return out
