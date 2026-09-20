"""Tool registry: allowlists, result model, timeout wrapper."""
import asyncio
import logging
from typing import Any

from pydantic import BaseModel

from app.schemas import Evidence

logger = logging.getLogger(__name__)

TOOL_TIMEOUT_S = 10


class ToolResult(BaseModel):
    ok: bool
    data: Any
    summary: str
    evidence: list[Evidence] = []


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Any] = {}
        self._allowlists: dict[str, list[str]] = {}

    def register(self, name: str, fn: Any, agents: list[str] | None = None) -> None:
        self._tools[name] = fn
        for agent in (agents or []):
            self._allowlists.setdefault(agent, []).append(name)

    async def call(self, agent: str, tool_name: str, args: dict) -> ToolResult:
        allowed = self._allowlists.get(agent, [])
        if tool_name not in allowed:
            logger.warning("Agent %s tried to call disallowed tool %s", agent, tool_name)
            return ToolResult(ok=False, data=None, summary=f"Tool {tool_name} not allowed for {agent}")

        fn = self._tools.get(tool_name)
        if not fn:
            return ToolResult(ok=False, data=None, summary=f"Tool {tool_name} not found")

        try:
            result = await asyncio.wait_for(fn(**args), timeout=TOOL_TIMEOUT_S)
            return result
        except asyncio.TimeoutError:
            return ToolResult(ok=False, data=None, summary=f"Tool {tool_name} timed out")
        except Exception as e:  # noqa: BLE001
            logger.warning("Tool %s failed: %s", tool_name, e)
            return ToolResult(ok=False, data=None, summary=f"Tool {tool_name} error: {e}")


def openai_tool_schemas(tools: list[tuple[str, type[BaseModel], str]]) -> list[dict]:
    """Convert list of (name, args_model, description) to OpenAI tool format."""
    schemas = []
    for name, model, description in tools:
        schema = model.model_json_schema()
        schemas.append({
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": schema,
            },
        })
    return schemas
