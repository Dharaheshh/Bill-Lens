"""
Agent base: the only agent loop (SPEC §8.0).
run_agent implements the step-based tool-calling loop with fallback.
"""
import json
import logging
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel

from app.llm.client import LLMUnavailable, llm_client
from app.orchestrator.events import RunContext

logger = logging.getLogger(__name__)


def _extract_json(text: str) -> str:
    """Extract JSON object from text, handling markdown code fences."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1])
    # Find first { to last }
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1:
        return text[start : end + 1]
    return text


class AgentSpec(BaseModel):
    name: str
    system_prompt: str
    tools: list[str]
    max_steps: int
    model_role: str = "agent"


async def run_agent(
    spec: AgentSpec,
    payload: dict,
    ctx: RunContext,
    validate: Callable,
    fallback: Callable,
    tool_registry: Any | None = None,
) -> Any:
    """The single agent loop per SPEC §8.0."""
    msgs = [
        {"role": "system", "content": spec.system_prompt},
        {"role": "user", "content": json.dumps(payload, default=str)},
    ]

    ctx.emit(spec.name, "stage_start", f"{spec.name}: starting (max {spec.max_steps} steps)")

    for step in range(spec.max_steps):
        try:
            # Build tool schemas for this agent if tool_registry provided
            tool_schemas = None
            if tool_registry and spec.tools:
                tool_schemas = [t for t in (tool_registry.get_schemas(spec.tools) or [])]

            resp = await llm_client.chat(
                msgs,
                role=spec.model_role,
                tools=tool_schemas or None,
                temperature=0,
            )
            ctx.emit(spec.name, "llm_call", f"{spec.name}: step {step + 1}")
        except LLMUnavailable:
            ctx.emit(spec.name, "warning", f"{spec.name}: LLM unavailable at step {step + 1}")
            return fallback(ctx)

        if resp.tool_calls:
            msgs.append({"role": "assistant", "content": resp.text or "", "tool_calls": [
                {"id": tc["id"], "type": "function", "function": {"name": tc["name"], "arguments": json.dumps(tc["args"])}}
                for tc in resp.tool_calls
            ]})
            for call in resp.tool_calls:
                ctx.emit(spec.name, "tool_call", f"{call['name']}({str(call['args'])[:80]})", data=call["args"])
                if tool_registry:
                    result = await tool_registry.call(spec.name, call["name"], call["args"])
                    ids = ctx.evidence.add(result.evidence)
                    ctx.emit(spec.name, "tool_result", result.summary, data={"evidence_ids": ids})
                    msgs.append({
                        "role": "tool",
                        "tool_call_id": call["id"],
                        "content": json.dumps(result.data, default=str),
                    })
        else:
            # Final answer
            try:
                json_text = _extract_json(resp.text)
                out = validate(json_text, ctx)
                ctx.emit(spec.name, "stage_end", f"{spec.name}: done")
                return out
            except Exception as e:  # noqa: BLE001
                logger.warning("%s: validation failed at step %d: %s", spec.name, step, e)
                msgs.append({"role": "user", "content": "Your output was not valid JSON for the schema. Return ONLY valid JSON."})
                continue

    ctx.emit(spec.name, "warning", f"{spec.name}: step cap reached, using fallback")
    return fallback(ctx)
