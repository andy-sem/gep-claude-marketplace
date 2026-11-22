"""Calls the real Jev for the live tests (marker `live_jev`). Never used by the default run."""

import os
from collections.abc import Mapping
from typing import Any, ClassVar

from destructive_guard.jev.client import JevClient
from destructive_guard.jev.config import JevConfig
from destructive_guard.jev.decider import JevDecider
from destructive_guard.jev.request import JevRequest


class LiveJev:
    """The only place that knows how a decision is made (LJ0: build_state + ask_jev + jev_decision)."""

    DEFAULT_MAX_REQUESTS = 80
    requests = 0
    # Rows for the end-of-session report: {"section": str, "cells": list[str]}.
    rows: ClassVar[list[dict[str, Any]]] = []

    @classmethod
    def max_requests(cls) -> int:
        try:
            return int(os.environ.get("LIVE_JEV_MAX_REQUESTS", "") or cls.DEFAULT_MAX_REQUESTS)
        except ValueError:
            return cls.DEFAULT_MAX_REQUESTS

    @classmethod
    def count_request(cls) -> None:
        cls.requests += 1
        if cls.requests > cls.max_requests():
            raise AssertionError(f"more than LIVE_JEV_MAX_REQUESTS={cls.max_requests()} live requests in one run")

    @staticmethod
    def config(env: Mapping[str, str]) -> dict:
        return JevConfig.read({"GATE_JEV": "1", **env})

    @classmethod
    def raw(cls, call: Mapping[str, Any], env: Mapping[str, str]) -> tuple[dict, dict | None, dict]:
        """(cfg, state, result): the client's {probabilities, usage, latencyMs} or {error, latencyMs}."""
        cfg = cls.config(env)
        state = JevRequest.build_state(call)
        if state is None:
            return cfg, None, {"error": "skipped: .env reference", "latencyMs": 0}
        cls.count_request()
        return cfg, state, JevClient().ask_jev(state, cfg)

    @classmethod
    def decide(cls, call: Mapping[str, Any], env: Mapping[str, str]) -> dict:
        """{decision: "ask" | "none" | None (error), risk, top, probabilities, latencyMs, error}."""
        cfg, _state, result = cls.raw(call, env)
        probabilities = result.get("probabilities")
        if not probabilities:
            return {
                "decision": None,
                "risk": None,
                "top": None,
                "probabilities": None,
                "latencyMs": result["latencyMs"],
                "error": result.get("error"),
            }
        prompt = JevRequest._prompt_of(cfg)
        risk = sum(probabilities[c] for c in prompt["ask"])
        top = max(probabilities, key=lambda c: probabilities[c])
        jev = JevDecider.jev_decision(probabilities, cfg)
        return {
            "decision": "ask" if jev and jev["decision"] == "ask" else "none",
            "risk": risk,
            "top": top,
            "probabilities": probabilities,
            "latencyMs": result["latencyMs"],
            "error": None,
        }

    @classmethod
    def report(cls, section: str, *cells: Any) -> None:
        cls.rows.append({"section": section, "cells": [str(c) for c in cells]})

    @classmethod
    def markdown(cls) -> str:
        out: list[str] = []
        sections: dict[str, list[list[str]]] = {}
        for row in cls.rows:
            sections.setdefault(row["section"], []).append(row["cells"])
        for name, rows in sections.items():
            width = max(len(r) for r in rows)
            header = rows[0] if name.startswith("corpus") else None
            out.append(f"### {name}\n")
            if header is not None:
                rows = rows[1:]
                out.append("| " + " | ".join(header) + " |")
                out.append("|" + " --- |" * len(header))
            else:
                out.append("| " + " | ".join(["value"] * width) + " |")
                out.append("|" + " --- |" * width)
            out.extend("| " + " | ".join(r) + " |" for r in rows)
            out.append("")
        return "\n".join(out)
