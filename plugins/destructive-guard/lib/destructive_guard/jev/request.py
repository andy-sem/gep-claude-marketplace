"""The Jev request: state sent to Jev, the request body and the parsed answer."""

import json
from collections.abc import Mapping
from typing import Any

from .prompt import JevPrompt
from .redactor import Redactor


class JevRequest:
    """Builds the request state and body and parses Jev's answer."""

    MAX_COMMAND_CHARS = 8000
    MAX_INPUT_CHARS = 8000
    MAX_SCRIPTS_BYTES = 65536

    @staticmethod
    def _dumps(obj: Any) -> str:
        return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))

    _default_prompt: dict | None = None

    @classmethod
    def _prompt_of(cls, cfg: Mapping[str, Any]) -> dict:
        if cfg.get("prompt"):
            return cfg["prompt"]
        if cls._default_prompt is None:
            cls._default_prompt = JevPrompt.builtin_prompt(JevPrompt.DEFAULT_PROMPT)
        return cls._default_prompt

    @staticmethod
    def request_body(state: dict, model: str, prompt: dict) -> dict:
        return {
            "model": model,
            "state": {**state, "context": prompt["context"]},
            "questions": {
                prompt["question"]: {
                    "type": "choice",
                    "instructions": prompt["instructions"],
                    "criteria": prompt["criteria"],
                }
            },
        }

    @staticmethod
    def _byte_length(text: str) -> int:
        return len(text.encode("utf-8", "replace"))

    @classmethod
    def scripts_payload(cls, files: list[dict]) -> tuple[list[dict], list[str]]:
        """Scripts go to Jev in collection order, redacted, up to 64 KB in total: the file that crosses
        the cap is cut, the rest are left out. The notes say what was cut."""
        scripts: list[dict] = []
        notes: list[str] = []
        used = 0
        cut_path: str | None = None
        omitted: list[str] = []
        for file in files:
            content = Redactor.redact_script(file["content"])
            size = cls._byte_length(content)
            if file.get("truncated"):
                notes.append(f"{file['path']} cut at 64 KB")
            if cut_path or omitted:
                omitted.append(file["path"])
            elif used + size <= cls.MAX_SCRIPTS_BYTES:
                scripts.append({"path": file["path"], "content": content})
                used += size
            elif used < cls.MAX_SCRIPTS_BYTES:
                room = cls.MAX_SCRIPTS_BYTES - used
                cut = content.encode("utf-8", "replace")[:room].decode("utf-8", "replace")
                scripts.append({"path": file["path"], "content": cut})
                used = cls.MAX_SCRIPTS_BYTES
                cut_path = file["path"]
            else:
                omitted.append(file["path"])
        if cut_path or omitted:
            parts = []
            if cut_path:
                parts.append(f"{cut_path} truncated")
            if omitted:
                parts.append(f"omitted: {', '.join(omitted)}")
            notes.append(f"scripts cut at 64 KB total: {'; '.join(parts)}")
        return scripts, notes

    @staticmethod
    def problem_notes(problems: list[dict]) -> list[str]:
        """One note per file the gate could not read safely, so that Jev does not take an empty `scripts`
        list for "nothing to read". Exempt files are left out, and so are files cut at 64 KB (the cut is
        noted already). The text is redacted like a script."""
        return [
            f"{Redactor.redact_script(p['path'])} not read: {p['reason']}"
            for p in problems
            if not p.get("exempt") and p.get("reason") != "exceeds 64 KB"
        ]

    @classmethod
    def build_state(cls, call: Mapping[str, Any]) -> dict | None:
        """The request state for a call, or None when the call must not be sent (a Bash command that
        references an .env file). `call` is {tool: "Bash", command, scripts, problems} or {tool, input}."""
        if call["tool"] == "Bash":
            redacted = Redactor.redact(call["command"])
            if redacted is None:
                return None
            notes = []
            if len(redacted) > cls.MAX_COMMAND_CHARS:
                notes.append(f"command cut to {cls.MAX_COMMAND_CHARS} of {len(redacted)} characters")
            scripts, script_notes = cls.scripts_payload(call.get("scripts") or [])
            return {
                "tool": "Bash",
                "command": redacted[:cls.MAX_COMMAND_CHARS],
                "scripts": scripts,
                "notes": [*notes, *script_notes, *cls.problem_notes(call.get("problems") or [])],
            }
        text = Redactor.redact_mcp_input(call.get("input"))
        notes = []
        if len(text) > cls.MAX_INPUT_CHARS:
            notes.append(f"input cut to {cls.MAX_INPUT_CHARS} of {len(text)} characters")
        return {"tool": call["tool"], "input": text[:cls.MAX_INPUT_CHARS], "notes": notes}

    @staticmethod
    def _get(obj: Any, key: str) -> Any:
        return obj.get(key) if isinstance(obj, dict) else None

    @classmethod
    def parse_answer(cls, body: Any, prompt: dict | None = None) -> dict | None:
        """The probabilities map, or None when the response is malformed."""
        prompt = prompt or cls._prompt_of({})
        choices = list(prompt["criteria"])
        answer = cls._get(cls._get(body, "answers"), prompt["question"])
        probs = cls._get(answer, "probabilities")
        if cls._get(answer, "type") != "choice" or not isinstance(probs, dict):
            return None
        total = 0.0
        for choice in choices:
            p = probs.get(choice)
            if isinstance(p, bool) or not isinstance(p, (int, float)) or not 0 <= p <= 1:
                return None
            total += p
        if abs(total - 1) > 0.05:
            return None
        return {c: probs[c] for c in choices}
