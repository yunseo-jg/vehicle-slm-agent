"""MCP SDK 2.x 도구를 LangChain 도구로 변환한다."""

from __future__ import annotations

import json
from typing import Any

from langchain_core.tools import StructuredTool


def _text_content(result: Any) -> str:
    texts = [getattr(block, "text", "") for block in result.content]
    return "".join(texts)


async def load_mcp_tools(client: Any) -> list[StructuredTool]:
    """연결된 MCP 2.x Client가 노출하는 도구를 LangChain 형식으로 변환한다."""

    listed = await client.list_tools()
    tools: list[StructuredTool] = []

    for mcp_tool in listed.tools:
        name = mcp_tool.name

        async def call_mcp_tool(_name: str = name, **kwargs: Any) -> dict[str, Any]:
            result = await client.call_tool(_name, kwargs)
            if isinstance(result.structured_content, dict):
                return result.structured_content
            text = _text_content(result)
            try:
                parsed = json.loads(text)
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                pass
            return {
                "status": "error" if result.is_error else "ok",
                "code": "unknown_tool" if result.is_error else None,
                "message": text,
                "state_after": {},
            }

        tools.append(
            StructuredTool.from_function(
                coroutine=call_mcp_tool,
                name=name,
                description=mcp_tool.description or name,
                args_schema=mcp_tool.input_schema,
            )
        )

    return tools
