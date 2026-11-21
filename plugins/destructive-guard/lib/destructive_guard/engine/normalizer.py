"""Peels wrappers and runners off a simple command (the normalisation step of the gate engine)."""

import re
from typing import Any, ClassVar

from ..errors import UnparsableError
from ..rules.rule_loader import Rules
from ..shell.cmd import Cmd
from ..shell.tokenizer import ShellTokenizer


class CommandNormalizer:
    """Normalises simple commands against one set of rules."""

    # `$` that is not the start of `$(`: an expansion whose value is unknown.
    _DOLLAR_EXPANSION = re.compile(r"\$(?!\()")
    # Wrapper options that take a value (given separately, attached, or as `--opt=v`).
    # Only options that always take a value are listed: wrongly consuming a word could
    # hide the real program, so ambiguous ones are left out (the later-token scan in
    # eval_tokens is the backstop when a value is consumed anyway).
    WRAPPER_VALUE_OPTS: ClassVar[dict[str, list[str]]] = {
        "sudo": [
            "-u", "-g", "-h", "-p", "-C", "-D", "-R", "-T", "-U", "-r", "-t",
            "--user", "--group", "--host", "--prompt", "--close-from", "--chdir",
            "--role", "--type", "--other-user", "--command-timeout",
        ],
        "doas": ["-u", "-C"],
        "env": ["-u", "-C", "-S", "--unset", "--chdir", "--split-string"],
        "timeout": ["-s", "-k", "--signal", "--kill-after"],
        "time": ["-f", "-o", "--format", "--output"],
        "exec": ["-a"],
        "nice": ["-n", "--adjustment"],
        "watch": ["-n", "--interval"],
        "caffeinate": ["-t", "-w"],
        "stdbuf": ["-i", "-o", "-e", "--input", "--output", "--error"],
        "ionice": ["-c", "-n", "-p", "-P", "-u", "--class", "--classdata"],
        "xargs": [
            "-n", "-L", "-P", "-I", "-d", "-E", "-s", "-a", "--max-args", "--max-lines", "--max-procs",
            "--delimiter", "--eof", "--arg-file", "--max-chars", "--process-slot-var",
        ],
    }

    _VERSIONED = re.compile(r"(@?[^@]+)@[^/]*")

    def __init__(self, rules: Rules) -> None:
        self.rules = rules

    @staticmethod
    def strip_options(tokens: list[str], value_opts: list[str] | None = None, shell_opts: list[str] | None = None) -> dict:
        """Strips leading options from `tokens`. Options in `value_opts` take a value (given separately,
        attached to a short option, or as `--opt=value`); short options may be clustered (`-iu root`). An
        option in `shell_opts` makes the remaining words a shell command string, returned as `shell`."""
        value_opts = value_opts or []
        shell_opts = shell_opts or []
        seen: list[str] = []
        values: dict[str, str | None] = {}
        k = 0
        n = len(tokens)
        while k < n:
            tok = tokens[k]
            if not tok.startswith("-") or tok == "-":
                break
            k += 1
            if tok == "--":
                break
            if tok.startswith("--"):
                eq = tok.find("=")
                name = tok if eq == -1 else tok[:eq]
                seen.append(name)
                if name in shell_opts:
                    words = tokens[k:] if eq == -1 else [tok[eq + 1 :], *tokens[k:]]
                    return {"rest": [], "seen": seen, "values": values, "shell": " ".join(words)}
                if eq != -1:
                    values[name] = tok[eq + 1 :]
                elif name in value_opts:
                    values[name] = tokens[k] if k < n else None
                    k += 1
                continue
            for c in range(1, len(tok)):
                name = f"-{tok[c]}"
                attached = tok[c + 1 :]
                seen.append(name)
                if name in shell_opts:
                    words = [attached, *tokens[k:]] if attached else tokens[k:]
                    return {"rest": [], "seen": seen, "values": values, "shell": " ".join(words)}
                if name in value_opts:
                    if attached:
                        values[name] = attached
                    else:
                        values[name] = tokens[k] if k < n else None
                        k += 1
                    break
        return {"rest": tokens[k:], "seen": seen, "values": values}

    @staticmethod
    def split_words(s: str) -> list[str]:
        """Words of an `env -S` string (no expansions allowed: their value is unknown)."""
        if "$" in s or "`" in s:
            raise UnparsableError("dynamic env -S string")
        out: list[Cmd] = []
        ShellTokenizer.scan_list(s, 0, None, out, ShellTokenizer.MAX_DEPTH, None)
        return [w for c in out for w in c]

    @classmethod
    def strip_version(cls, token: str) -> str:
        """`tool@1.2.3` / `@scope/pkg@latest` -> the bin name without its version."""
        m = cls._VERSIONED.fullmatch(token)
        return m.group(1) if m else token

    def strip_wrappers(self, raw_tokens: list[str]) -> dict[str, Any]:
        """Drops leading assignments and wrappers (`sudo`, `env`, …) off a simple command and stops at
        anything else, runners included. `argsFromInput` is set when a wrapper supplies extra arguments
        (`xargs`), so the real argument list is unknown. `final` is set when the wrapper turned the rest
        into a shell command (`watch`)."""
        tokens = raw_tokens
        args_from_input = False
        for _ in range(64):
            k = 0
            while k < len(tokens) and ShellTokenizer.ASSIGNMENT_RE.match(tokens[k]):
                k += 1
            tokens = tokens[k:]
            if not tokens:
                return {"tokens": tokens, "argsFromInput": args_from_input}
            base = Cmd.basename(tokens[0])
            if base not in self.rules["wrappers"]:
                return {"tokens": tokens, "argsFromInput": args_from_input}
            opts = self.strip_options(tokens[1:], self.WRAPPER_VALUE_OPTS.get(base, []))
            rest = opts["rest"]
            if base == "env":
                split = opts["values"].get("-S")
                if split is None:
                    split = opts["values"].get("--split-string")
                if split is not None:
                    rest = [*self.split_words(split), *rest]
            elif base == "timeout":
                rest = rest[1:]  # duration
            elif base == "xargs":
                args_from_input = True
            elif base == "watch" and "-x" not in opts["seen"] and "--exec" not in opts["seen"]:
                # watch hands its joined arguments to `sh -c`
                cmd = ["sh", "-c", " ".join(rest)] if rest else []
                return {"tokens": cmd, "argsFromInput": args_from_input, "final": True}
            tokens = rest
        raise UnparsableError("wrapper nesting too deep")

    @staticmethod
    def shell_script_index(tokens: list[str]) -> int:
        """The index of the script operand of `bash|sh|zsh …`, or -1 when the shell runs a `-c` string
        or reads stdin."""
        if not tokens or Cmd.basename(tokens[0]) not in ShellTokenizer.SHELLS:
            return -1
        info = ShellTokenizer.parse_shell(tokens)
        return info["index"] if info.get("script") else -1

    def nested_shell_string(self, raw_tokens: list[str]) -> str | None:
        """The shell command string a simple command hands to a shell through wrappers and runners
        (`watch bash x.sh`, `timeout 5 bash -c '…'`, `npx -c '…'`), or None. A plain `bash -c '…'` is also
        found by `split_command`; a string with an unresolvable `$` expansion cannot be analysed: None."""
        try:
            n = self.normalize(raw_tokens)
        except Exception:  # noqa: BLE001 (any failure: no string)
            return None
        if not n["tokens"] or Cmd.basename(n["tokens"][0]) not in ShellTokenizer.SHELLS:
            return None
        s = ShellTokenizer.parse_shell(n["tokens"]).get("command")
        if not s or self._DOLLAR_EXPANSION.search(s):
            return None
        return s

    def normalize(self, raw_tokens: list[str]) -> dict[str, Any]:
        """Peels wrappers and runners (`npx`, `pnpm exec`, …) off a simple command."""
        tokens = raw_tokens
        args_from_input = False
        for _ in range(64):
            w = self.strip_wrappers(tokens)
            tokens = w["tokens"]
            args_from_input = args_from_input or w["argsFromInput"]
            if w.get("final") or not tokens:
                return {"tokens": tokens, "argsFromInput": args_from_input}
            base = Cmd.basename(tokens[0])
            runner = next((r for r in self.rules["runners"] if r["program"] == base), None)
            if runner is None:
                return {"tokens": tokens, "argsFromInput": args_from_input}

            def strip(lst: list[str], runner=runner) -> dict:
                return self.strip_options(lst, runner["valueOptions"], runner["shellOptions"])

            opts = strip(tokens[1:])
            if "shell" not in opts and opts["rest"] and opts["rest"][0] in runner["subcommands"]:
                opts = strip(opts["rest"][1:])
            elif "shell" not in opts and not runner["bareBin"]:
                return {"tokens": tokens, "argsFromInput": args_from_input}  # a runner command that runs no bin
            if "shell" in opts:
                return {"tokens": ["sh", "-c", opts["shell"]], "argsFromInput": args_from_input}
            tokens = [self.strip_version(opts["rest"][0]), *opts["rest"][1:]] if opts["rest"] else []
        raise UnparsableError("wrapper nesting too deep")
