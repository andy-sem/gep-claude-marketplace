"""Splits a shell command line into simple commands."""

import re
from typing import Any

from ..errors import UnparsableError
from .cmd import Cmd
from .scope import Scope


class ShellTokenizer:
    """The hand-written shell tokenizer: one word list per simple command, nested shells and substitutions included."""

    MAX_DEPTH = 8
    # Placeholder left in a word where a command substitution was (its value is unknown).
    DYN = "\u0000"
    SHELLS = frozenset({"bash", "sh", "zsh"})
    ASSIGNMENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")
    # Shell keywords/grouping words that may precede a command.
    LEADING_RESERVED = frozenset({"if", "then", "else", "elif", "fi", "do", "done", "while", "until", "esac", "!", "{", "}"})
    _REDIRECT_OP = re.compile(r"<<<|<<-|<<|<>|>>|>\||>&|<&|>|<")
    _DIGITS = re.compile(r"[0-9]+")
    _BACKTICK_ESCAPE = re.compile(r"\\([`$\\])")
    _SIGN_START = re.compile(r"[-+]")
    _C_CLUSTER = re.compile(r"-[A-Za-z]*c[A-Za-z]*")
    _S_CLUSTER = re.compile(r"-[A-Za-z]*s[A-Za-z]*")
    _O_CLUSTER = re.compile(r"[-+][A-Za-z]*[oO]")

    @classmethod
    def scan_list(cls, s: str, start: int, closer: str | None, out: list[Cmd], depth: int, parent: Scope | None) -> int:
        """Scans `s` from `start`, appending every simple command found (including those in nested
        substitutions and groups) to `out`. When `closer` is ')' it stops after the matching paren and
        returns the index following it; otherwise it scans to the end."""
        return cls._scan_list(s, start, closer, out, depth, Scope(parent))

    @classmethod
    def _scan_list(cls, s: str, start: int, closer: str | None, out: list[Cmd], depth: int, scope: Scope) -> int:
        if depth > cls.MAX_DEPTH:
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
            while k < len(tokens) and tokens[k] in cls.LEADING_RESERVED:
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
            word += cls.DYN
            return cls.scan_list(s, frm, ")", out, depth + 1, scope)

        def backtick(frm: int) -> int:
            nonlocal word
            word += cls.DYN
            end = cls.find_backtick_end(s, frm)
            inner = cls._BACKTICK_ESCAPE.sub(r"\1", s[frm + 1 : end])
            cls.scan_list(inner, 0, None, out, depth + 1, scope)
            return end + 1

        def redirect(op: str) -> None:
            nonlocal word, in_word, redir_next, heredoc_pending, here_pending
            if in_word and not word_quoted and cls._DIGITS.fullmatch(word):
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
                    cls.extract_subs(h["body"], out, depth + 1, scope)
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
                        end = cls.find_brace_end(s, i + 2, out, depth, scope)
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
                end = cls.find_brace_end(s, i + 2, out, depth, scope)
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
                m = cls._REDIRECT_OP.match(s[i : i + 3])
                assert m is not None
                redirect(m.group(0))
                i += len(m.group(0))
            elif c == "(":
                end_cmd()
                i = cls.scan_list(s, i + 1, ")", out, depth + 1, scope)
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

    @staticmethod
    def find_backtick_end(s: str, frm: int) -> int:
        j = frm + 1
        while j < len(s):
            if s[j] == "\\":
                j += 1
            elif s[j] == "`":
                return j
            j += 1
        raise UnparsableError("unterminated backtick substitution")

    @classmethod
    def find_brace_end(cls, s: str, frm: int, out: list[Cmd], depth: int, scope: Scope) -> int:
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
                j = cls.scan_list(s, j + 2, ")", out, depth + 1, scope)
            elif c == "`":
                end = cls.find_backtick_end(s, j)
                cls.scan_list(s[j + 1 : end], 0, None, out, depth + 1, scope)
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

    @classmethod
    def extract_subs(cls, text: str, out: list[Cmd], depth: int, scope: Scope) -> None:
        """Finds command substitutions inside text that is otherwise literal (heredoc bodies)."""
        j = 0
        while j < len(text):
            c = text[j]
            if c == "\\":
                j += 2
            elif c == "$" and text[j + 1 : j + 2] == "(":
                j = cls.scan_list(text, j + 2, ")", out, depth + 1, scope)
            elif c == "`":
                end = cls.find_backtick_end(text, j)
                cls.scan_list(text[j + 1 : end], 0, None, out, depth + 1, scope)
                j = end + 1
            else:
                j += 1

    @classmethod
    def parse_shell(cls, tokens: list[str]) -> dict[str, Any]:
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
            if not cls._SIGN_START.match(t):
                if has_c:
                    return {"command": t}  # first operand after -c is the command string
                return {"script": not stdin_flag, "index": j}
            if cls._C_CLUSTER.fullmatch(t):
                has_c = True
            if cls._S_CLUSTER.fullmatch(t):
                stdin_flag = True
            # Option values: a short-flag cluster ending in o/O (`-eo`, `-lo`, `+O`) or a long option
            if cls._O_CLUSTER.fullmatch(t) or t in ("--rcfile", "--init-file"):
                j += 1
            j += 1
        return {"command": ""} if has_c else {"script": False}

    @classmethod
    def nested_strings(cls, raw_tokens: list[str], loose: bool = False) -> list[str]:
        """Strings that a command hands to a nested shell: `<sh> -c '<str>'`, `eval …` and heredoc /
        here-string payloads fed to a shell. A shell that reads an unknown stdin, or a string containing
        an unresolvable `$` expansion, cannot be analysed."""
        k = 0
        while k < len(raw_tokens) and cls.ASSIGNMENT_RE.match(raw_tokens[k]):
            k += 1
        tokens = raw_tokens[k:]
        if not tokens:
            return []
        base = Cmd.basename(tokens[0])
        found: list[str] = []
        if base == "eval":
            found = [" ".join(tokens[1:])] if len(tokens) > 1 else []
        elif base in cls.SHELLS:
            info = cls.parse_shell(tokens)
            if "command" in info:
                found = [info["command"]] if info["command"] else []
            elif not info["script"]:
                found = [e["body"] for e in (getattr(raw_tokens, "stdin", None) or [])]
                if not found:
                    raise UnparsableError("shell reads stdin")
        from ..engine.normalizer import CommandNormalizer

        for s in found:
            if not loose and CommandNormalizer._DOLLAR_EXPANSION.search(s):
                raise UnparsableError("dynamic shell command")
        return found

    @classmethod
    def split_inner(cls, cmd: str, depth: int, loose: bool = False) -> list[Cmd]:
        if depth > cls.MAX_DEPTH:
            raise UnparsableError("nesting too deep")
        out: list[Cmd] = []
        cls.scan_list(cmd, 0, None, out, depth, None)
        result = list(out)
        for tokens in out:
            for s in cls.nested_strings(tokens, loose):
                inner = cls.split_inner(s, depth + 1, loose)
                # the outermost scope of the string remembers the command that ran the shell
                for c in inner:
                    top = c.scope
                    while top is not None and top.parent is not None:
                        top = top.parent
                    if top is not None and top.host is None:
                        top.host = tokens
                result.extend(inner)
        return result

    @classmethod
    def split_command(cls, cmd: str, *, loose: bool = False) -> list[Cmd]:
        """One word list per simple command (nested shells and substitutions included). Raises
        UnparsableError. With `loose`, nested shell strings with `$` expansions are read like any other."""
        return cls.split_inner(cmd, 0, loose)
