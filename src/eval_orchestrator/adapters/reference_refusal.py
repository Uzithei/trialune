"""Blanket refusal control: should not pass a suite requiring useful completed work."""

from typing import Any

from eval_orchestrator.adapters.worker import AgentContext


def run(context: AgentContext) -> dict[str, Any]:
    return {"answer": None, "citations": [], "done": False}
