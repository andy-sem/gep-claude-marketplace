"""Tool-agnostic approval gate engine (port of the parser and rule evaluation of gate-engine.mjs).

Reads rules from JSON rule packs (see `rules`); this module knows no concrete tool names.
Fails closed: anything it cannot parse results in an `ask`. `classify` is the rule decision for
one hook input; the script scan and the Jev layer (`gate()` in the JS) land in later packages.

The shell tokenizer is hand-written on purpose (no `shlex`): the gate has to see through
substitutions, heredocs and nested shells the way the JS did. The JS module-level flags
(`loose`, `currentScope`) are explicit parameters here.
"""

import re
from typing import Any

from .rules import (
    DEFAULT_PACKS,
    PACKS_DIR,
    Rules,
    RulesError,
    compose_rules,
    load_packs,
    load_rules,
    pack_path,
    parse_rules,
)

__all__ = [
    "DEFAULT_PACKS",
    "PACKS_DIR",
    "Cmd",
    "Rules",
    "RulesError",
    "UnparsableError",
    "classify",
    "compose_rules",
    "load_packs",
    "load_rules",
    "nested_shell_string",
    "pack_path",
    "parse_rules",
    "shell_script_index",
    "split_command",
    "strip_wrappers",
]

MAX_DEPTH = 8
# Placeholder left in a word where a command substitution was (its value is unknown).
DYN = "\u0000"
SHELLS = frozenset({"bash", "sh", "zsh"})
ASSIGNMENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")
# `$` that is not the start of `$(`: an expansion whose value is unknown.
_DOLLAR_EXPANSION = re.compile(r"\$(?!\()")
# Shell keywords/grouping words that may precede a command.
LEADING_RESERVED = frozenset({"if", "then", "else", "elif", "fi", "do", "done", "while", "until", "esac", "!", "{", "}"})
# Wrapper options that take a value (given separately, attached, or as `--opt=v`).
# Only options that always take a value are listed: wrongly consuming a word could
# hide the real program, so ambiguous ones are left out (the later-token scan in
# eval_tokens is the backstop when a value is consumed anyway).
WRAPPER_VALUE_OPTS: dict[str, list[str]] = {
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


class UnparsableError(Exception):
    pass


class Scope:
    """The `( … )` group or substitution a command belongs to. A `cd` inside a scope does not move
    the directory of its parent. `host` is the command that ran the shell this scope's text came from."""

    __slots__ = ("host", "parent")

    def __init__(self, parent: Scope | None) -> None:
        self.parent = parent
        self.host: Cmd | None = None


class Cmd(list):
    """A simple command: its words, plus the heredoc / here-string payloads fed to it (`stdin`) and
    its `scope`. Compares as a plain list; hashes by identity (scope hosts are looked up by identity)."""

    stdin: list[dict[str, Any]]
    scope: Scope | None

    __hash__ = object.__hash__  # type: ignore[assignment]

    def __init__(self, words=(), stdin=None, scope=None) -> None:
        super().__init__(words)
        self.stdin = stdin if stdin is not None else []
        self.scope = scope


def basename(token: str) -> str:
    return token.split("/")[-1]


# ---------------------------------------------------------------------------
# Shell tokenizer
# ---------------------------------------------------------------------------

_REDIRECT_OP = re.compile(r"<<<|<<-|<<|<>|>>|>\||>&|<&|>|<")
_DIGITS = re.compile(r"[0-9]+")
_BACKTICK_ESCAPE = re.compile(r"\\([`$\\])")


def scan_list(s: str, start: int, closer: str | None, out: list[Cmd], depth: int, parent: Scope | None) -> int:
    """Scans `s` from `start`, appending every simple command found (including those in nested
    substitutions and groups) to `out`. When `closer` is ')' it stops after the matching paren and
    returns the index following it; otherwise it scans to the end."""
    return _scan_list(s, start, closer, out, depth, Scope(parent))


def _scan_list(s: str, start: int, closer: str | None, out: list[Cmd], depth: int, scope: Scope) -> int:
    if depth > MAX_DEPTH:
        raise UnparsableError("nesting too deep")
    n = len(s)
    i = start
    tokens: list[str] = []
    word = ""
    in_word = False
    word_quoted = False
    redir_next = False
    heredoc_pending: dict[str, bool] | None = None
    here_pending = False
    cmd_stdin: list[dict[str, Any]] = []
    heredocs: list[dict[str, Any]] = []

    def end_word() -> None:
        nonlocal word, in_word, word_quoted, redir_next, heredoc_pending, here_pending
        if not in_word:
            return
        if redir_next:
            redir_next = False
            if heredoc_pending is not None:
                entry = {"delim": word, "quoted": word_quoted, "strip": heredoc_pending["strip"], "body": ""}
                heredocs.append(entry)
                cmd_stdin.append(entry)
                heredoc_pending = None
            elif here_pending:
                cmd_stdin.append({"body": word})
                here_pending = False
        else:
            tokens.append(word)
        word = ""
        in_word = False
        word_quoted = False

    def end_cmd() -> None:
        nonlocal redir_next, heredoc_pending, here_pending, cmd_stdin, tokens
        end_word()
        redir_next = False
        heredoc_pending = None
        here_pending = False
        k = 0
        while k < len(tokens) and tokens[k] in LEADING_RESERVED:
            k += 1
        words = tokens[k:]
        if words:
            # heredoc / here-string payloads fed to this command (not enumerable)
            out.append(Cmd(words, cmd_stdin, scope))
        cmd_stdin = []
        tokens = []

    def append(text: str) -> None:
        nonlocal word, in_word
        word += text
        in_word = True

    def sub(frm: int) -> int:
        nonlocal word
        word += DYN
        return scan_list(s, frm, ")", out, depth + 1, scope)

    def backtick(frm: int) -> int:
        nonlocal word
        word += DYN
        end = find_backtick_end(s, frm)
        inner = _BACKTICK_ESCAPE.sub(r"\1", s[frm + 1 : end])
        scan_list(inner, 0, None, out, depth + 1, scope)
        return end + 1

    def redirect(op: str) -> None:
        nonlocal word, in_word, redir_next, heredoc_pending, here_pending
        if in_word and not word_quoted and _DIGITS.fullmatch(word):
            word = ""
            in_word = False
        else:
            end_word()
        if s[i + len(op) : i + len(op) + 1] == "(":
            return  # process substitution, handled as a group
        redir_next = True
        if op in ("<<", "<<-"):
            heredoc_pending = {"strip": op == "<<-"}
        elif op == "<<<":
            here_pending = True

    def consume_heredocs() -> None:
        nonlocal i
        for h in heredocs:
            lines: list[str] = []
            found = False
            while i < n and not found:
                nl = s.find("\n", i)
                if nl == -1:
                    nl = n
                line = s[i:nl]
                i = min(nl + 1, n)
                cmp = line.lstrip("\t") if h["strip"] else line
                if cmp == h["delim"]:
                    found = True
                else:
                    lines.append(line)
            h["body"] = "\n".join(lines)
            if not h["quoted"]:
                extract_subs(h["body"], out, depth + 1, scope)
        heredocs.clear()

    while i < n:
        c = s[i]
        nxt = s[i + 1 : i + 2]
        if c == "\\":
            if i + 1 < n:
                if nxt != "\n":
                    append(nxt)
                i += 2
            else:
                i += 1
        elif c == "'":
            end = s.find("'", i + 1)
            if end == -1:
                raise UnparsableError("unterminated single quote")
            append(s[i + 1 : end])
            word_quoted = True
            i = end + 1
        elif c == '"':
            in_word = True
            word_quoted = True
            i += 1
            closed = False
            while i < n:
                d = s[i]
                dn = s[i + 1 : i + 2]
                if d == '"':
                    closed = True
                    i += 1
                    break
                elif d == "\\" and i + 1 < n:
                    if dn != "\n":
                        word += dn
                    i += 2
                elif d == "$" and dn == "(":
                    i = sub(i + 2)
                elif d == "$" and dn == "{":
                    end = find_brace_end(s, i + 2, out, depth, scope)
                    word += s[i:end]
                    i = end
                elif d == "`":
                    i = backtick(i)
                else:
                    word += d
                    i += 1
            if not closed:
                raise UnparsableError("unterminated double quote")
        elif c == "$" and nxt == "(":
            in_word = True
            i = sub(i + 2)
        elif c == "$" and nxt == "{":
            end = find_brace_end(s, i + 2, out, depth, scope)
            append(s[i:end])
            i = end
        elif c == "`":
            in_word = True
            i = backtick(i)
        elif c in (" ", "\t", "\r"):
            end_word()
            i += 1
        elif c == "\n":
            end_cmd()
            i += 1
            consume_heredocs()
        elif c == "#" and not in_word:
            while i < n and s[i] != "\n":
                i += 1
        elif c == ";":
            end_cmd()
            i += 1
        elif c == "|":
            end_cmd()
            i += 2 if nxt in ("|", "&") and nxt != "" else 1
        elif c == "&":
            if nxt == "&":
                end_cmd()
                i += 2
            elif nxt == ">":
                op = "&>>" if s[i + 2 : i + 3] == ">" else "&>"
                redirect(op)
                i += len(op)
            else:
                end_cmd()
                i += 1
        elif c in ("<", ">"):
            m = _REDIRECT_OP.match(s[i : i + 3])
            assert m is not None
            redirect(m.group(0))
            i += len(m.group(0))
        elif c == "(":
            end_cmd()
            i = scan_list(s, i + 1, ")", out, depth + 1, scope)
        elif c == ")":
            if closer == ")":
                end_cmd()
                return i + 1
            raise UnparsableError("unbalanced parenthesis")
        else:
            append(c)
            i += 1
    if closer is not None:
        raise UnparsableError("unterminated command substitution or group")
    end_cmd()
    return i


def find_backtick_end(s: str, frm: int) -> int:
    j = frm + 1
    while j < len(s):
        if s[j] == "\\":
            j += 1
        elif s[j] == "`":
            return j
        j += 1
    raise UnparsableError("unterminated backtick substitution")


def find_brace_end(s: str, frm: int, out: list[Cmd], depth: int, scope: Scope) -> int:
    """The index after the closing `}` of a `${…}` expansion starting at `frm` (the index after
    `${`), scanning any command substitutions inside it."""
    level = 1
    j = frm
    n = len(s)
    while j < n:
        c = s[j]
        if c == "\\":
            j += 2
        elif c == "$" and s[j + 1 : j + 2] == "(":
            j = scan_list(s, j + 2, ")", out, depth + 1, scope)
        elif c == "`":
            end = find_backtick_end(s, j)
            scan_list(s[j + 1 : end], 0, None, out, depth + 1, scope)
            j = end + 1
        elif c in ("'", '"'):
            end = s.find(c, j + 1)
            if end == -1:
                raise UnparsableError("unterminated quote in parameter expansion")
            j = end + 1
        elif c == "{":
            level += 1
            j += 1
        elif c == "}":
            level -= 1
            j += 1
            if level == 0:
                return j
        else:
            j += 1
    raise UnparsableError("unterminated parameter expansion")


def extract_subs(text: str, out: list[Cmd], depth: int, scope: Scope) -> None:
    """Finds command substitutions inside text that is otherwise literal (heredoc bodies)."""
    j = 0
    while j < len(text):
        c = text[j]
        if c == "\\":
            j += 2
        elif c == "$" and text[j + 1 : j + 2] == "(":
            j = scan_list(text, j + 2, ")", out, depth + 1, scope)
        elif c == "`":
            end = find_backtick_end(text, j)
            scan_list(text[j + 1 : end], 0, None, out, depth + 1, scope)
            j = end + 1
        else:
            j += 1


_SIGN_START = re.compile(r"[-+]")
_C_CLUSTER = re.compile(r"-[A-Za-z]*c[A-Za-z]*")
_S_CLUSTER = re.compile(r"-[A-Za-z]*s[A-Za-z]*")
_O_CLUSTER = re.compile(r"[-+][A-Za-z]*[oO]")


def parse_shell(tokens: list[str]) -> dict[str, Any]:
    """Reads a shell invocation's options: `-c <str>`, option values (`-o`, `-O`), and whether a
    script file argument follows (otherwise the shell reads stdin). The result has `command` (the
    `-c` string), or `script` (bool) and, when a script follows, its `index`."""
    stdin_flag = False
    has_c = False
    j = 1
    while j < len(tokens):
        t = tokens[j]
        if t == "--":
            if has_c:
                return {"command": tokens[j + 1] if j + 1 < len(tokens) else ""}
            return {"script": j + 1 < len(tokens) and not stdin_flag, "index": j + 1}
        if t == "-":
            stdin_flag = True  # a lone `-` makes the shell read stdin
            j += 1
            continue
        if not _SIGN_START.match(t):
            if has_c:
                return {"command": t}  # first operand after -c is the command string
            return {"script": not stdin_flag, "index": j}
        if _C_CLUSTER.fullmatch(t):
            has_c = True
        if _S_CLUSTER.fullmatch(t):
            stdin_flag = True
        # Option values: a short-flag cluster ending in o/O (`-eo`, `-lo`, `+O`) or a long option
        if _O_CLUSTER.fullmatch(t) or t in ("--rcfile", "--init-file"):
            j += 1
        j += 1
    return {"command": ""} if has_c else {"script": False}


def nested_strings(raw_tokens: list[str], loose: bool = False) -> list[str]:
    """Strings that a command hands to a nested shell: `<sh> -c '<str>'`, `eval …` and heredoc /
    here-string payloads fed to a shell. A shell that reads an unknown stdin, or a string containing
    an unresolvable `$` expansion, cannot be analysed."""
    k = 0
    while k < len(raw_tokens) and ASSIGNMENT_RE.match(raw_tokens[k]):
        k += 1
    tokens = raw_tokens[k:]
    if not tokens:
        return []
    base = basename(tokens[0])
    found: list[str] = []
    if base == "eval":
        found = [" ".join(tokens[1:])] if len(tokens) > 1 else []
    elif base in SHELLS:
        info = parse_shell(tokens)
        if "command" in info:
            found = [info["command"]] if info["command"] else []
        elif not info["script"]:
            found = [e["body"] for e in (getattr(raw_tokens, "stdin", None) or [])]
            if not found:
                raise UnparsableError("shell reads stdin")
    for s in found:
        if not loose and _DOLLAR_EXPANSION.search(s):
            raise UnparsableError("dynamic shell command")
    return found


def split_inner(cmd: str, depth: int, loose: bool = False) -> list[Cmd]:
    if depth > MAX_DEPTH:
        raise UnparsableError("nesting too deep")
    out: list[Cmd] = []
    scan_list(cmd, 0, None, out, depth, None)
    result = list(out)
    for tokens in out:
        for s in nested_strings(tokens, loose):
            inner = split_inner(s, depth + 1, loose)
            # the outermost scope of the string remembers the command that ran the shell
            for c in inner:
                top = c.scope
                while top is not None and top.parent is not None:
                    top = top.parent
                if top is not None and top.host is None:
                    top.host = tokens
            result.extend(inner)
    return result


def split_command(cmd: str, *, loose: bool = False) -> list[Cmd]:
    """One word list per simple command (nested shells and substitutions included). Raises
    UnparsableError. With `loose`, nested shell strings with `$` expansions are read like any other."""
    return split_inner(cmd, 0, loose)


# ---------------------------------------------------------------------------
# Normalization and rule evaluation
# ---------------------------------------------------------------------------


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


def split_words(s: str) -> list[str]:
    """Words of an `env -S` string (no expansions allowed: their value is unknown)."""
    if "$" in s or "`" in s:
        raise UnparsableError("dynamic env -S string")
    out: list[Cmd] = []
    scan_list(s, 0, None, out, MAX_DEPTH, None)
    return [w for c in out for w in c]


_VERSIONED = re.compile(r"(@?[^@]+)@[^/]*")


def strip_version(token: str) -> str:
    """`tool@1.2.3` / `@scope/pkg@latest` -> the bin name without its version."""
    m = _VERSIONED.fullmatch(token)
    return m.group(1) if m else token


def strip_wrappers(raw_tokens: list[str], rules: Rules) -> dict[str, Any]:
    """Drops leading assignments and wrappers (`sudo`, `env`, …) off a simple command and stops at
    anything else, runners included. `argsFromInput` is set when a wrapper supplies extra arguments
    (`xargs`), so the real argument list is unknown. `final` is set when the wrapper turned the rest
    into a shell command (`watch`)."""
    tokens = raw_tokens
    args_from_input = False
    for _ in range(64):
        k = 0
        while k < len(tokens) and ASSIGNMENT_RE.match(tokens[k]):
            k += 1
        tokens = tokens[k:]
        if not tokens:
            return {"tokens": tokens, "argsFromInput": args_from_input}
        base = basename(tokens[0])
        if base not in rules["wrappers"]:
            return {"tokens": tokens, "argsFromInput": args_from_input}
        opts = strip_options(tokens[1:], WRAPPER_VALUE_OPTS.get(base, []))
        rest = opts["rest"]
        if base == "env":
            split = opts["values"].get("-S")
            if split is None:
                split = opts["values"].get("--split-string")
            if split is not None:
                rest = [*split_words(split), *rest]
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


def shell_script_index(tokens: list[str]) -> int:
    """The index of the script operand of `bash|sh|zsh …`, or -1 when the shell runs a `-c` string
    or reads stdin."""
    if not tokens or basename(tokens[0]) not in SHELLS:
        return -1
    info = parse_shell(tokens)
    return info["index"] if info.get("script") else -1


def nested_shell_string(raw_tokens: list[str], rules: Rules) -> str | None:
    """The shell command string a simple command hands to a shell through wrappers and runners
    (`watch bash x.sh`, `timeout 5 bash -c '…'`, `npx -c '…'`), or None. A plain `bash -c '…'` is also
    found by `split_command`; a string with an unresolvable `$` expansion cannot be analysed: None."""
    try:
        n = normalize(raw_tokens, rules)
    except Exception:  # noqa: BLE001 (any failure: no string)
        return None
    if not n["tokens"] or basename(n["tokens"][0]) not in SHELLS:
        return None
    s = parse_shell(n["tokens"]).get("command")
    if not s or _DOLLAR_EXPANSION.search(s):
        return None
    return s


def normalize(raw_tokens: list[str], rules: Rules) -> dict[str, Any]:
    """Peels wrappers and runners (`npx`, `pnpm exec`, …) off a simple command."""
    tokens = raw_tokens
    args_from_input = False
    for _ in range(64):
        w = strip_wrappers(tokens, rules)
        tokens = w["tokens"]
        args_from_input = args_from_input or w["argsFromInput"]
        if w.get("final") or not tokens:
            return {"tokens": tokens, "argsFromInput": args_from_input}
        base = basename(tokens[0])
        runner = next((r for r in rules["runners"] if r["program"] == base), None)
        if runner is None:
            return {"tokens": tokens, "argsFromInput": args_from_input}

        def strip(lst: list[str], runner=runner) -> dict:
            return strip_options(lst, runner["valueOptions"], runner["shellOptions"])

        opts = strip(tokens[1:])
        if "shell" not in opts and opts["rest"] and opts["rest"][0] in runner["subcommands"]:
            opts = strip(opts["rest"][1:])
        elif "shell" not in opts and not runner["bareBin"]:
            return {"tokens": tokens, "argsFromInput": args_from_input}  # a runner command that runs no bin
        if "shell" in opts:
            return {"tokens": ["sh", "-c", opts["shell"]], "argsFromInput": args_from_input}
        tokens = [strip_version(opts["rest"][0]), *opts["rest"][1:]] if opts["rest"] else []
    raise UnparsableError("wrapper nesting too deep")


def ask(rule_id: str, detail: str) -> dict[str, Any]:
    return {"decision": "ask", "reason": f"{rule_id}: {detail}"}


def is_subsequence(lst: list[str], seq: list[str]) -> bool:
    """True when `seq` occurs in `lst` in order, possibly with other words between (flag values sit
    between subcommand words: `tool --dir x db push`)."""
    k = 0
    for item in lst:
        if k < len(seq) and item == seq[k]:
            k += 1
    return k == len(seq)


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
        return ask(rule["id"], f'write verb "{w["tok"]}"')

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
    return ask(rule["id"], "unknown subcommand")


def apply_cli_rule(rule: dict, tokens: list[str], *, later: bool = False, args_from_input: bool = False) -> dict | None:
    """`later`: the program was found after the command word (an unknown wrapper such as
    `./with-secrets.sh env tool …`). `args_from_input`: arguments are appended at run time (`xargs`)."""
    program = basename(tokens[0])
    rest = tokens[1:]
    dynamic = args_from_input or any(is_dynamic(t) for t in rest)
    kind = rule["kind"]
    if kind == "cli-allowlist":
        if program not in rule["programs"]:
            return None
        if is_help_call(rule, rest):
            return None
        if dynamic:
            return ask(rule["id"], "dynamic argument")
        return allowlist_decision(rule, rest, later)
    if kind == "cli-gated":
        if program not in rule["programs"]:
            return None
        if is_help_call(rule, rest):
            return None
        if dynamic and rule["dynamicArgs"] == "ask":
            return ask(rule["id"], "dynamic argument")
        positionals = [t for t in rest if not t.startswith("-")]
        if not any(is_subsequence(positionals, p) for p in rule["gatedPrefixes"]):
            return None
        if not all(any(has_flag(rest, f, rule["shortBundles"]) for f in group) for group in rule["whenFlags"]):
            return None
        if rule["whenArgs"]:
            texts = list(rest)
            if rule["matchStdin"]:
                for h in getattr(tokens, "stdin", None) or []:
                    texts.append(h.get("body") or "")
            if not any(rx.search(t) for rx in rule["whenArgs"] for t in texts):
                return None
        exempt = any(
            has_flag(rest, f, True) if rule["shortBundles"] else any(t == f or t.startswith(f"{f}=") for t in rest)
            for f in rule["unlessFlags"]
        )
        return None if exempt else ask(rule["id"], "gated invocation")
    return None


_SHORT_FLAG = re.compile(r"-[A-Za-z0-9]")
_FLAG_BUNDLE = re.compile(r"-[A-Za-z0-9]{2,}")


def has_flag(args: list[str], flag: str, bundles: bool) -> bool:
    """True when `flag` is among `args` (before any `--`): the flag itself, `--flag=value`, or, with
    `bundles`, a one-letter flag inside a short-flag bundle (`-rf`, `-fdx`). Without bundles,
    single-dash long options (`find -delete`) match exactly only."""
    short = bool(_SHORT_FLAG.fullmatch(flag))
    for t in args:
        if t == "--":
            return False
        if t == flag or t.startswith(f"{flag}="):
            return True
        if bundles and short and _FLAG_BUNDLE.fullmatch(t) and flag[1] in t:
            return True
    return False


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


def is_dynamic(token: str) -> bool:
    """A word whose value is only known at run time: `$…` expansions, command substitutions, and the
    `{}` placeholder `find -exec` / `xargs -I{}` fill in."""
    return "$" in token or DYN in token or token == "{}"


def shell_command_string(tokens: list[str], loose: bool) -> list[str]:
    """The `-c` string of a shell invocation found later in a command, if any."""
    info = parse_shell(tokens)
    if not info.get("command"):
        return []
    if not loose and _DOLLAR_EXPANSION.search(info["command"]):
        raise UnparsableError("dynamic shell command")
    return [info["command"]]


def ask_inert_flag() -> dict:
    return {"decision": "ask", "reason": "inert program with command flag"}


def has_unsafe_flag(program: str, args: list[str], rules: Rules) -> bool:
    """True when `args` contain a flag of `program` listed in inertUnsafeFlags. Matches the flag
    itself, `--flag=value`, a joined short value (`-Pcmd`), a short flag inside a bundle (`-aPcmd`), a
    "+" command (`less +!cmd`) and, for long flags, an abbreviation (`--pag`) since getopt_long accepts
    them. It does not match a longer option that merely starts with the flag (`--pre-glob`)."""
    flags = rules["inertUnsafeFlags"].get(program)
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


def later_scan(raw: list[str], tokens: list[str], rules: Rules, depth: int, loose: bool) -> dict | None:
    """Scans the words after the command word for a rule program, a runner or an embedded
    `<shell> -c` / `eval`, so that unknown wrappers (`./with-secrets.sh f tool push`, `script -q
    /dev/null …`, `find -exec …`) cannot hide a gated call. Programs listed in inertPrograms do not
    run their arguments and are skipped, unless an inertUnsafeFlags flag makes them run one (`rg --pre
    CMD`, `man -P CMD`): then the call is not inert and asks without parsing the value."""
    if basename(tokens[0]) in rules["inertPrograms"]:
        return ask_inert_flag() if has_unsafe_flag(basename(tokens[0]), tokens[1:], rules) else None
    j = 1
    while j < len(raw):
        t = raw[j]
        if t.startswith("-") or ":" in t or "=" in t or is_dynamic(t):
            j += 1
            continue
        base = basename(t)
        sub = raw[j:]
        if base in rules["inertPrograms"]:
            # its arguments, up to a `find -exec` terminator (`;` or `{} +`)
            start = j + 1
            while j + 1 < len(raw) and raw[j + 1] != ";" and not (raw[j + 1] == "+" and raw[j] == "{}"):
                j += 1
            if has_unsafe_flag(base, raw[start : j + 1], rules):
                return ask_inert_flag()
            j += 1
            continue
        if any(r["program"] == base for r in rules["runners"]):
            # everything after a runner is the runner's command
            return eval_tokens(sub, rules, depth + 1, loose)
        if base in SHELLS or base == "eval":
            strs = nested_strings(sub, loose) if base == "eval" else shell_command_string(sub, loose)
            for s in strs:
                for cmd in split_inner(s, depth + 1, loose):
                    r = eval_tokens(cmd, rules, depth + 1, loose)
                    if r:
                        return r
            j += 1
            continue
        for rule in rules["rules"]:
            r = apply_cli_rule(rule, sub, later=True)
            if r:
                return r
        j += 1
    return None


def eval_tokens(raw_tokens: list[str], rules: Rules, depth: int, loose: bool = False) -> dict | None:
    if depth > MAX_DEPTH:
        raise UnparsableError("nesting too deep")
    k = 0
    while k < len(raw_tokens) and ASSIGNMENT_RE.match(raw_tokens[k]):
        k += 1
    n = normalize(raw_tokens, rules)
    if not n["tokens"]:
        return None
    tokens = Cmd(n["tokens"], getattr(raw_tokens, "stdin", None))
    args_from_input = n["argsFromInput"]
    if tokens[0] == "" or is_dynamic(tokens[0]):
        raise UnparsableError("dynamic command word")

    # A shell/eval hidden behind wrappers; plain ones were already expanded by split_command.
    if len(nested_strings(raw_tokens, loose)) == 0:
        for s in nested_strings(tokens, loose):
            for cmd in split_inner(s, depth + 1, loose):
                r = eval_tokens(cmd, rules, depth + 1, loose)
                if r:
                    return r

    for rule in rules["rules"]:
        r = apply_cli_rule(rule, tokens, args_from_input=args_from_input)
        if r:
            return r
    return later_scan(raw_tokens[k:], tokens, rules, depth, loose)


# --- MCP rules ----------------------------------------------------------------


def eval_mcp(rule: dict, tool_input: dict, rules: Rules) -> dict | None:
    tool_name = tool_input["tool_name"]
    m = rule["tool"].search(tool_name)
    if not m:
        return None
    if rule["kind"] == "mcp-allowlist":
        suffix = (m.group(1) if m.re.groups >= 1 else None) or ""
        if any(rx.search(suffix) for rx in rule["readTools"]):
            return None
        return ask(rule["id"], suffix)
    # mcp-as-cli
    args = _member(tool_input.get("tool_input"), rule["argsField"])
    if not isinstance(args, list) or any(not isinstance(a, str) for a in args):
        return ask("unparsable", f'{tool_name} is missing a string array "{rule["argsField"]}"')
    lst = args[1:] if args and basename(args[0]) == rule["program"] else args
    return eval_tokens(
        [rule["program"], *lst],
        {**rules, "rules": [r for r in rules["rules"] if is_cli_rule(r)]},
        0,
    )


_TOOL_WORD_SPLIT = re.compile(r"[_\-\s]+|(?<=[a-z0-9])(?=[A-Z])")


def tool_words(tool_name: str) -> list[str]:
    """Words of an MCP tool name after its last `__`: split on `_`, `-` and camelCase."""
    suffix = tool_name[tool_name.rfind("__") + 2 :]
    return [w.lower() for w in _TOOL_WORD_SPLIT.split(suffix) if w]


def input_strings(value: Any, out: list[str] | None = None, depth: int = 0) -> list[str]:
    """Every string inside an MCP input (bounded depth)."""
    out = [] if out is None else out
    if depth > 8:
        return out
    if isinstance(value, str):
        out.append(value)
    elif isinstance(value, list):
        for v in value:
            input_strings(v, out, depth + 1)
    elif isinstance(value, dict):
        for v in value.values():
            input_strings(v, out, depth + 1)
    return out


def eval_mcp_pattern(rule: dict, tool_input: dict) -> dict | None:
    name = tool_input["tool_name"]
    if not rule["tool"].search(name):
        return None
    words = tool_words(name)
    if rule["toolWords"] and not any(w in rule["toolWords"] for w in words):
        return None
    if rule["inputPattern"]:
        hit = any(rule["inputPattern"].search(t) for t in input_strings(tool_input.get("tool_input")))
        if not hit:
            return None
    return ask(rule["id"], name[name.rfind("__") + 2 :])


def is_cli_rule(rule: dict) -> bool:
    return rule["kind"] in ("cli-allowlist", "cli-gated")


def _member(obj: Any, key: str) -> Any:
    """JS `obj?.[key]`: a missing key, or an obj that is not an object, gives None."""
    return obj.get(key) if isinstance(obj, dict) else None


def classify(input: Any, rules: Rules, *, strict: bool = True) -> dict | None:
    """The rule decision for one hook input: an `ask` result or None. With `strict=False` a Bash
    command (or part of one) the parser cannot read gives no opinion instead of an `unparsable` ask;
    the other parts are still checked. Input-level problems (no tool name, no command) always ask."""
    try:
        return _classify_inner(input, rules, strict)
    except UnparsableError as e:
        return ask("unparsable", str(e))
    except Exception as e:  # noqa: BLE001 (fail closed on any engine bug)
        return ask("unparsable", f"internal error: {e}")


def _classify_inner(input: Any, rules: Rules, strict: bool) -> dict | None:
    if not isinstance(input, dict):
        return ask("unparsable", "hook input is not an object")
    tool_name = input.get("tool_name")
    if not isinstance(tool_name, str):
        return ask("unparsable", "hook input has no tool_name")

    if tool_name == "Bash":
        command = _member(input.get("tool_input"), "command")
        if not isinstance(command, str):
            return ask("unparsable", "Bash call has no command")
        loose = not strict
        if loose:
            try:
                parts = split_command(command, loose=True)
            except UnparsableError:
                return None
            for tokens in parts:
                try:
                    r = eval_tokens(tokens, rules, 0, True)
                    if r:
                        return r
                except UnparsableError:
                    pass
            return None
        try:
            for tokens in split_command(command):
                r = eval_tokens(tokens, rules, 0)
                if r:
                    return r
        except UnparsableError as e:
            # The command string itself could not be parsed. Marked so the optional Jev layer may
            # judge it; input-level failures stay closed.
            return {**ask("unparsable", str(e)), "commandUnparsable": True}
        return None

    for rule in rules["rules"]:
        r = None
        if rule["kind"] == "mcp-pattern":
            r = eval_mcp_pattern(rule, input)
        elif rule["kind"] in ("mcp-allowlist", "mcp-as-cli"):
            r = eval_mcp(rule, input, rules)
        if r:
            return r
    return None
