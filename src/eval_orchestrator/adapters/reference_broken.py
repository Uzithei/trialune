"""Deliberately incorrect qualification agent; never presented as a model result."""

from typing import Any

from eval_orchestrator.adapters.worker import AgentContext


def run(context: AgentContext) -> dict[str, Any]:
    if context.tools:
        context.call_tool("unauthorized_tool", {})
    return {
        "supplier": "invented",
        "invoice": "invented",
        "total": -1,
        "answer": "unsupported claim",
        "citations": ["nonexistent"],
        "done": True,
    }
