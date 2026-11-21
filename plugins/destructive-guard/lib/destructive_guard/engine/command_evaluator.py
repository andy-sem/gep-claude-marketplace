"""Evaluates the tokens of one shell command against the CLI rules, recursing into nested shells."""

from ..errors import UnparsableError
from ..rules.rule_loader import Rules
from ..shell.cmd import Cmd
from ..shell.tokenizer import ShellTokenizer
from ..verdict import Verdict
from .cli_rule_matcher import CliRuleMatcher
from .normalizer import CommandNormalizer


class CommandEvaluator:
    """Evaluates commands against one set of rules."""

    def __init__(self, rules: Rules) -> None:
        self.rules = rules
        self.normalizer = CommandNormalizer(rules)
        self.matcher = CliRuleMatcher(rules)

    @staticmethod
    def shell_command_string(tokens: list[str], loose: bool) -> list[str]:
        """The `-c` string of a shell invocation found later in a command, if any."""
        info = ShellTokenizer.parse_shell(tokens)
        if not info.get("command"):
            return []
        if not loose and CommandNormalizer._DOLLAR_EXPANSION.search(info["command"]):
            raise UnparsableError("dynamic shell command")
        return [info["command"]]

    def later_scan(self, raw: list[str], tokens: list[str], depth: int, loose: bool) -> dict | None:
        """Scans the words after the command word for a rule program, a runner or an embedded
        `<shell> -c` / `eval`, so that unknown wrappers (`./with-secrets.sh f tool push`, `script -q
        /dev/null …`, `find -exec …`) cannot hide a gated call. Programs listed in inertPrograms do not
        run their arguments and are skipped, unless an inertUnsafeFlags flag makes them run one (`rg --pre
        CMD`, `man -P CMD`): then the call is not inert and asks without parsing the value."""
        if Cmd.basename(tokens[0]) in self.rules["inertPrograms"]:
            return Verdict.inert_flag() if self.matcher.has_unsafe_flag(Cmd.basename(tokens[0]), tokens[1:]) else None
        j = 1
        while j < len(raw):
            t = raw[j]
            if t.startswith("-") or ":" in t or "=" in t or CliRuleMatcher.is_dynamic(t):
                j += 1
                continue
            base = Cmd.basename(t)
            sub = raw[j:]
            if base in self.rules["inertPrograms"]:
                # its arguments, up to a `find -exec` terminator (`;` or `{} +`)
                start = j + 1
                while j + 1 < len(raw) and raw[j + 1] != ";" and not (raw[j + 1] == "+" and raw[j] == "{}"):
                    j += 1
                if self.matcher.has_unsafe_flag(base, raw[start : j + 1]):
                    return Verdict.inert_flag()
                j += 1
                continue
            if any(r["program"] == base for r in self.rules["runners"]):
                # everything after a runner is the runner's command
                return self.eval_tokens(sub, depth + 1, loose)
            if base in ShellTokenizer.SHELLS or base == "eval":
                strs = ShellTokenizer.nested_strings(sub, loose) if base == "eval" else CommandEvaluator.shell_command_string(sub, loose)
                for s in strs:
                    for cmd in ShellTokenizer.split_inner(s, depth + 1, loose):
                        r = self.eval_tokens(cmd, depth + 1, loose)
                        if r:
                            return r
                j += 1
                continue
            for rule in self.rules["rules"]:
                r = CliRuleMatcher.apply_cli_rule(rule, sub, later=True)
                if r:
                    return r
            j += 1
        return None

    def eval_tokens(self, raw_tokens: list[str], depth: int, loose: bool = False) -> dict | None:
        if depth > ShellTokenizer.MAX_DEPTH:
            raise UnparsableError("nesting too deep")
        k = 0
        while k < len(raw_tokens) and ShellTokenizer.ASSIGNMENT_RE.match(raw_tokens[k]):
            k += 1
        n = self.normalizer.normalize(raw_tokens)
        if not n["tokens"]:
            return None
        tokens = Cmd(n["tokens"], getattr(raw_tokens, "stdin", None))
        args_from_input = n["argsFromInput"]
        if tokens[0] == "" or CliRuleMatcher.is_dynamic(tokens[0]):
            raise UnparsableError("dynamic command word")

        # A shell/eval hidden behind wrappers; plain ones were already expanded by split_command.
        if len(ShellTokenizer.nested_strings(raw_tokens, loose)) == 0:
            for s in ShellTokenizer.nested_strings(tokens, loose):
                for cmd in ShellTokenizer.split_inner(s, depth + 1, loose):
                    r = self.eval_tokens(cmd, depth + 1, loose)
                    if r:
                        return r

        for rule in self.rules["rules"]:
            r = CliRuleMatcher.apply_cli_rule(rule, tokens, args_from_input=args_from_input)
            if r:
                return r
        return self.later_scan(raw_tokens[k:], tokens, depth, loose)
