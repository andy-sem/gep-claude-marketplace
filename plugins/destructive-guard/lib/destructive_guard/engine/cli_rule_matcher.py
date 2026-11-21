"""Applies CLI rules (allowlist and gated kinds) to one normalised command."""

import re
from typing import Any

from ..rules.rule_loader import Rules
from ..shell.cmd import Cmd
from ..shell.tokenizer import ShellTokenizer
from ..verdict import Verdict


class CliRuleMatcher:
    """Matches commands against one set of rules."""

    def __init__(self, rules: Rules) -> None:
        self.rules = rules

    @staticmethod
    def is_subsequence(lst: list[str], seq: list[str]) -> bool:
        """True when `seq` occurs in `lst` in order, possibly with other words between (flag values sit
        between subcommand words: `tool --dir x db push`)."""
        k = 0
        for item in lst:
            if k < len(seq) and item == seq[k]:
                k += 1
        return k == len(seq)

    @staticmethod
    def allowlist_decision(rule: dict, rest: list[str], later: bool) -> dict | None:
        """Read/write decision for an allowlisted program's arguments.

        - Words after a bare flag (`--zone list`, `-o ls`) may be flag values, and words after `--` are
          passed through: such "loose" words never establish a read, but still count as write verbs.
        - readPrefixes / readSequences are anchored at the first firm word (after any leading skipWords).
          Write verbs inside the matched command path ask; with a readSequence, words after it are
          arguments and are ignored; with a readPrefix any write verb asks.
        - Otherwise any write verb asks, a firm read verb passes, and anything else is an unknown
          subcommand (asked, except in `later` mode where only writes ask).
        """
        words: list[dict[str, Any]] = []
        loose = False
        passthrough = False
        for t in rest:
            if not passthrough and t == "--":
                passthrough = True
                continue
            if not passthrough and len(t) > 1 and t.startswith("-"):
                loose = "=" not in t
                continue
            words.append({"tok": t, "firm": not passthrough and not loose})
            loose = False

        def is_write(w: dict) -> bool:
            return w["tok"] in rule["writeVerbs"]

        def write_ask(w: dict) -> dict:
            return Verdict.ask(rule["id"], f'write verb "{w["tok"]}"')

        firm = [{**w, "i": i} for i, w in enumerate(words) if w["firm"]]
        s = 0
        while s < len(firm) and firm[s]["tok"] in rule["skipWords"]:
            s += 1

        def anchored(seq: list[str]) -> list[int] | None:
            if seq and len(seq) <= len(firm) - s and all(firm[s + k]["tok"] == x for k, x in enumerate(seq)):
                return [w["i"] for w in firm[s : s + len(seq)]]
            return None

        for prefix in rule["readPrefixes"]:
            m = anchored(prefix)
            if m is not None:
                w = next((w for i, w in enumerate(words) if i not in m and is_write(w)), None)
                return write_ask(w) if w else None
        for seq in rule["readSequences"]:
            m = anchored(seq)
            if m is not None:
                end = m[-1]
                w = next((w for i, w in enumerate(words) if i < end and i not in m and is_write(w)), None)
                return write_ask(w) if w else None
        w = next((w for w in words if is_write(w)), None)
        if w:
            return write_ask(w)
        if later:
            return None
        if any(w["tok"] in rule["readVerbs"] for w in firm):
            return None
        return Verdict.ask(rule["id"], "unknown subcommand")

    @classmethod
    def apply_cli_rule(cls, rule: dict, tokens: list[str], *, later: bool = False, args_from_input: bool = False) -> dict | None:
        """`later`: the program was found after the command word (an unknown wrapper such as
        `./with-secrets.sh env tool …`). `args_from_input`: arguments are appended at run time (`xargs`)."""
        program = Cmd.basename(tokens[0])
        rest = tokens[1:]
        dynamic = args_from_input or any(cls.is_dynamic(t) for t in rest)
        kind = rule["kind"]
        if kind == "cli-allowlist":
            if program not in rule["programs"]:
                return None
            if cls.is_help_call(rule, rest):
                return None
            if dynamic:
                return Verdict.ask(rule["id"], "dynamic argument")
            return cls.allowlist_decision(rule, rest, later)
        if kind == "cli-gated":
            if program not in rule["programs"]:
                return None
            if cls.is_help_call(rule, rest):
                return None
            if dynamic and rule["dynamicArgs"] == "ask":
                return Verdict.ask(rule["id"], "dynamic argument")
            positionals = [t for t in rest if not t.startswith("-")]
            if not any(cls.is_subsequence(positionals, p) for p in rule["gatedPrefixes"]):
                return None
            if not all(any(cls.has_flag(rest, f, rule["shortBundles"]) for f in group) for group in rule["whenFlags"]):
                return None
            if rule["whenArgs"]:
                texts = list(rest)
                if rule["matchStdin"]:
                    for h in getattr(tokens, "stdin", None) or []:
                        texts.append(h.get("body") or "")
                if not any(rx.search(t) for rx in rule["whenArgs"] for t in texts):
                    return None
            exempt = any(
                cls.has_flag(rest, f, True) if rule["shortBundles"] else any(t == f or t.startswith(f"{f}=") for t in rest)
                for f in rule["unlessFlags"]
            )
            return None if exempt else Verdict.ask(rule["id"], "gated invocation")
        return None

    _SHORT_FLAG = re.compile(r"-[A-Za-z0-9]")
    _FLAG_BUNDLE = re.compile(r"-[A-Za-z0-9]{2,}")

    @classmethod
    def has_flag(cls, args: list[str], flag: str, bundles: bool) -> bool:
        """True when `flag` is among `args` (before any `--`): the flag itself, `--flag=value`, or, with
        `bundles`, a one-letter flag inside a short-flag bundle (`-rf`, `-fdx`). Without bundles,
        single-dash long options (`find -delete`) match exactly only."""
        short = bool(cls._SHORT_FLAG.fullmatch(flag))
        for t in args:
            if t == "--":
                return False
            if t == flag or t.startswith(f"{flag}="):
                return True
            if bundles and short and cls._FLAG_BUNDLE.fullmatch(t) and flag[1] in t:
                return True
        return False

    @staticmethod
    def is_help_call(rule: dict, rest: list[str]) -> bool:
        """True when the arguments only ask the program for help, which changes nothing:

        - a `helpFlags` token before any `--`, unless the token before it is a bare flag (`--no-traffic
          --help`: the help flag could be that flag's value);
        - or the first firm positional word (after `skipWords`) is a `helpWords` entry.

        The flags are configured per rule: `-h` means host for psql and header for some object-storage CLIs.
        """
        flags = rule.get("helpFlags") or []
        words = rule.get("helpWords") or []
        if not flags and not words:
            return False
        skip = rule.get("skipWords") or []
        loose = False
        skipping = True
        for t in rest:
            if t == "--":
                return False
            if len(t) > 1 and t.startswith("-"):
                if t in flags and not loose:
                    return True
                loose = "=" not in t
                continue
            if not loose:
                if skipping and t in skip:
                    continue
                if skipping:
                    if t in words:
                        return True
                    skipping = False
            loose = False
        return False

    @staticmethod
    def is_dynamic(token: str) -> bool:
        """A word whose value is only known at run time: `$…` expansions, command substitutions, and the
        `{}` placeholder `find -exec` / `xargs -I{}` fill in."""
        return "$" in token or ShellTokenizer.DYN in token or token == "{}"

    def has_unsafe_flag(self, program: str, args: list[str]) -> bool:
        """True when `args` contain a flag of `program` listed in inertUnsafeFlags. Matches the flag
        itself, `--flag=value`, a joined short value (`-Pcmd`), a short flag inside a bundle (`-aPcmd`), a
        "+" command (`less +!cmd`) and, for long flags, an abbreviation (`--pag`) since getopt_long accepts
        them. It does not match a longer option that merely starts with the flag (`--pre-glob`)."""
        flags = self.rules["inertUnsafeFlags"].get(program)
        if not flags:
            return False

        def matches(a: str, f: str) -> bool:
            if f.startswith("--"):
                if not a.startswith("--"):
                    return False
                name = a.split("=")[0]
                return len(name) > 2 and f.startswith(name)
            if f.startswith("-"):
                return a.startswith("-") and not a.startswith("--") and f[1] in a
            return a.startswith(f)

        return any(matches(a, f) for a in args for f in flags)
