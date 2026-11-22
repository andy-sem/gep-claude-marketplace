"""Names, quoting and small helpers shared by the launcher."""

import json
import re
from collections.abc import Mapping, Sequence
from typing import Any


class LaunchNaming:
    """Session names, slugs, quoting and JS-style value helpers of the launcher."""

    # Whatever keyPattern says, a key is put into shell commands unquoted.
    MODEL_ALIASES = frozenset(("opus", "sonnet", "haiku"))
    _MODEL_ID = re.compile(r"claude-[a-z0-9.-]+")
    _SAFE_KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
    _SAFE_REF = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]*")
    _PLAIN_ARG = re.compile(r"[A-Za-z0-9_:./@-]+")
    MAX_SHORT = 40

    @staticmethod
    def _json(value: Any) -> str:
        """JS `JSON.stringify` for the values that appear in messages."""
        return json.dumps(value, ensure_ascii=False)

    @staticmethod
    def _js_string(value: Any) -> str:
        """JS `String(value)` for JSON-derived values."""
        if value is True:
            return "true"
        if value is False:
            return "false"
        if value is None:
            return "null"
        return str(value)

    @staticmethod
    def _get(obj: Any, key: str) -> Any:
        """`obj?.[key]`: None unless `obj` is a mapping holding the key."""
        return obj.get(key) if isinstance(obj, Mapping) else None

    @staticmethod
    def _first(*values: Any) -> Any:
        """JS `a ?? b ?? c`: the first value that is not None."""
        return next((v for v in values if v is not None), None)

    @classmethod
    def shell_quote(cls, value: Any) -> str:
        """POSIX single-quote escaping."""
        return "'" + cls._js_string(value).replace("'", "'\\''") + "'"

    @classmethod
    def apple_script_string(cls, value: Any) -> str:
        """Escape a string for use inside an AppleScript double-quoted literal."""
        return '"' + cls._js_string(value).replace("\\", "\\\\").replace('"', '\\"') + '"'

    @classmethod
    def is_safe_key(cls, key: Any) -> bool:
        """True when `key` is usable in commands, branch and file names."""
        return isinstance(key, str) and cls._SAFE_KEY.fullmatch(key) is not None and ".." not in key

    @classmethod
    def is_model(cls, value: Any) -> bool:
        """True when `value` is a model alias (`opus`, `sonnet`, `haiku`) or a `claude-...` id, safe in a shell line."""
        return isinstance(value, str) and (value in cls.MODEL_ALIASES or cls._MODEL_ID.fullmatch(value) is not None)

    @classmethod
    def short_summary(cls, summary: Any) -> str:
        """A ticket title reduced to a safe, short phrase.

        Every character outside `[A-Za-z0-9 .,:()/_-]` becomes a space (this drops quotes, `$`,
        backticks, backslashes and `!`, so the title is safe in the double quotes of the command
        and in an AppleScript literal), then it is cut at a word boundary. Same rule as section 3
        step 8 of the ticket skill.
        """
        clean = re.sub(r"[^A-Za-z0-9 .,:()/_-]", " ", "" if summary is None else cls._js_string(summary))
        clean = re.sub(r" +", " ", clean).strip()
        if len(clean) <= cls.MAX_SHORT:
            return clean
        window = clean[: cls.MAX_SHORT]
        if clean[cls.MAX_SHORT] == " ":
            return window
        space = window.rfind(" ")
        return (window[:space] if space > 0 else window).strip()

    @classmethod
    def session_name(cls, *, key: str, args: Sequence[str] = (), summary: Any = None) -> str:
        """Title of a session: tab title, `claude --name` and the Remote Control name.

        `<KEY> · <summary>` for a new ticket, `<KEY> resume · <summary>` for a run that is resumed;
        without a summary just the key (and purpose).
        """
        head = f"{key} resume" if "--resume" in args else key
        short = cls.short_summary(summary)
        return f"{head} · {short}" if short else head

    @classmethod
    def slugify(cls, title: Any) -> str:
        """Same rule as section 3 step 3 of the ticket skill."""
        slug = re.sub(r"[^a-z0-9]+", "-", ("" if title is None else cls._js_string(title)).lower())
        slug = slug.strip("-")[:40].rstrip("-")
        return slug or "work"
