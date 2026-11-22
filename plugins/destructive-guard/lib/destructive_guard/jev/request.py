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

    @classmethod
    def build_state(cls, call: Mapping[str, Any]) -> dict | None:
        """The request state for a call, or None when the call must not be sent: it mentions a .env file
        (the check runs on the raw payload before redaction). `call` is {tool: "Bash", command} or
        {tool, input}. The command text goes to Jev as it is, redacted; nothing is parsed."""
        if call["tool"] == "Bash":
            redacted = Redactor.redact(call["command"])
            if redacted is None:
                return None
            notes = []
            if len(redacted) > cls.MAX_COMMAND_CHARS:
                notes.append(f"command cut to {cls.MAX_COMMAND_CHARS} of {len(redacted)} characters")
            return {"tool": "Bash", "command": redacted[: cls.MAX_COMMAND_CHARS], "notes": notes}
        if Redactor.references_env_file(cls._dumps(call.get("input"))):
            return None
        text = Redactor.redact_mcp_input(call.get("input"))
        notes = []
        if len(text) > cls.MAX_INPUT_CHARS:
            notes.append(f"input cut to {cls.MAX_INPUT_CHARS} of {len(text)} characters")
        return {"tool": call["tool"], "input": text[: cls.MAX_INPUT_CHARS], "notes": notes}

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
