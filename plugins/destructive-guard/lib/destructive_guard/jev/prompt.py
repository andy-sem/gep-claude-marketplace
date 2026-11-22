"""The question Jev answers: built-in and custom prompt files."""

import json
import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ..errors import JevConfigError
from ..paths import ProjectDir
from .config import JevConfig


class JevPrompt:
    """Loads and validates Jev prompts (jev/*.json or GATE_JEV_PROMPT)."""

    PROMPTS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "jev"
    DEFAULT_PROMPT = "destructive"

    @staticmethod
    def validate_prompt(p: Any, where: str = "prompt") -> dict:
        """A prompt is {question, instructions, context, criteria, ask, safe}: `criteria` maps each choice
        to {description, examples}, `ask` lists the choices whose probabilities add up to the risk. `safe` is
        optional (the choices that are harmless; for the log only, the decision never reads it). Raises JevConfigError when the shape is wrong."""

        def bad(msg: str) -> None:
            raise JevConfigError(f"{where}: {msg}")

        if not isinstance(p, dict):
            bad("must be a JSON object")
        q = p.get("question")
        if not isinstance(q, str) or not re.fullmatch(r"[a-z][a-z0-9_]*", q):
            bad("question must be a snake_case id")
        ins = p.get("instructions")
        if not isinstance(ins, str) or not ins.strip():
            bad("instructions must be a non-empty string")
        ctx = p.get("context")
        if not isinstance(ctx, dict) or any(not isinstance(v, str) for v in ctx.values()):
            bad("context must be an object of strings")
        criteria = p.get("criteria")
        if not isinstance(criteria, dict):
            bad("criteria must be an object")
        choices = list(criteria)
        if len(choices) < 2:
            bad("criteria needs at least two choices")
        for c, o in criteria.items():
            if (
                not isinstance(o, dict)
                or not isinstance(o.get("description"), str)
                or not isinstance(o.get("examples"), list)
                or any(not isinstance(e, str) for e in o["examples"])
            ):
                bad(f"criteria.{c} needs a description and string examples")
        for key in ("ask", "safe"):
            if key == "safe" and "safe" not in p:
                continue
            items = p.get(key)
            if not isinstance(items, list) or not items or any(c not in choices for c in items):
                bad(f"{key} must be a non-empty list of criteria choices")
        if any(c in p.get("safe", []) for c in p["ask"]):
            bad("ask and safe must not overlap")
        return p

    @classmethod
    def _read_prompt_file(cls, path: str | Path, where: str) -> dict:
        try:
            parsed = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            raise JevConfigError(f"{where}: cannot read {path}: {e}") from None
        return cls.validate_prompt(parsed, where)

    @classmethod
    def builtin_prompt(cls, name: str) -> dict:
        """A built-in prompt by name (jev/<name>.json)."""
        if not re.fullmatch(r"[a-z0-9-]+", name):
            raise JevConfigError(f'unknown built-in Jev prompt "{name}"')
        return cls._read_prompt_file(cls.PROMPTS_DIR / f"{name}.json", f"prompt {name}")

    @classmethod
    def prompt_from_env(cls, env: Mapping[str, str], *, cwd: str | Path | None = None) -> dict:
        """GATE_JEV_PROMPT: a built-in name (default "destructive") or a path to a prompt JSON file
        (relative paths resolve against the project). GATE_JEV_INSTRUCTIONS, GATE_JEV_CONTEXT and
        GATE_JEV_POLICY then replace the question text, context.project and context.policy."""
        cwd = cwd if cwd is not None else os.getcwd()
        ref = JevConfig._optional(env, "GATE_JEV_PROMPT") or cls.DEFAULT_PROMPT
        if "/" in ref or ref.endswith(".json"):
            base = cls._read_prompt_file(ProjectDir.project_path(ref, env, cwd), "GATE_JEV_PROMPT")
        else:
            base = cls.builtin_prompt(ref)
        prompt = {**base, "context": dict(base["context"])}
        instructions = JevConfig._optional(env, "GATE_JEV_INSTRUCTIONS")
        if instructions:
            prompt["instructions"] = instructions
        project = JevConfig._optional(env, "GATE_JEV_CONTEXT")
        if project:
            prompt["context"]["project"] = project
        policy = JevConfig._optional(env, "GATE_JEV_POLICY")
        if policy:
            prompt["context"]["policy"] = policy
        return prompt
