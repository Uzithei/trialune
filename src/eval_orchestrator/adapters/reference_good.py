"""Deterministic qualification agent for the documented starter syntax. Not an AI model."""

import json
import re
from typing import Any

from eval_orchestrator.adapters.worker import AgentContext


def run(context: AgentContext) -> dict[str, Any]:
    if context.prompt.startswith("Extract invoice"):
        source = "\n".join(document["text"] for document in context.documents)
        values = dict(re.findall(r"^(Supplier|Invoice|Total): ([^\n]+)$", source, re.MULTILINE))
        return {
            "supplier": values.get("Supplier"),
            "invoice": values.get("Invoice"),
            "total": int(values["Total"]) if "Total" in values else None,
        }
    if context.prompt.startswith("Classify ticket"):
        content = " ".join(d["text"] for d in context.documents).casefold()
        return {
            "category": "billing"
            if "payment" in content
            else "technical"
            if "crash" in content
            else "other"
        }
    if context.prompt.startswith("According to the documents"):
        key = context.prompt.rsplit(" ", 1)[-1].rstrip("?")
        matches = []
        for document in context.documents:
            for line in document["text"].splitlines():
                if line.startswith(key + "="):
                    matches.append((line.split("=", 1)[1], document["id"]))
        if len({value for value, _ in matches}) == 1:
            return {"answer": matches[0][0], "citations": [matches[0][1]]}
        return {"answer": None, "citations": []}
    instruction = json.loads(context.prompt)
    if instruction.get("action") == "none":
        return {"done": False}
    result = context.call_tool(instruction["tool"], instruction["arguments"])
    if not result["ok"] and result["error"] in {"injected_failure", "timeout_outcome_unknown"}:
        result = context.call_tool(instruction["tool"], instruction["arguments"])
    return result
