"""MCP 서버의 도구를 LangChain 도구로 바꾼다. MCP Python SDK 2.x 의 Client 를 쓴다.

langchain-mcp-adapters 는 mcp<2 만 지원해서(0.3.2 기준) 이 프로젝트의 mcp 2.x 와 함께
import 할 수 없다. 그래서 필요한 부분만 여기서 직접 한다.

    async with Client(StdioServerParameters(command=..., args=[...])) as client:
        tools = await load_mcp_tools(client)
"""

from __future__ import annotations

import json

from langchain_core.tools import BaseTool, StructuredTool
from mcp import Client


async def load_mcp_tools(client: Client) -> list[BaseTool]:
    """연결된 MCP 서버의 도구 전부. client 가 열려 있는 동안만 호출할 수 있다."""
    listed = await client.list_tools()
    return [_to_langchain_tool(client, tool) for tool in listed.tools]


def _to_langchain_tool(client: Client, tool) -> BaseTool:
    name = tool.name

    async def call(**kwargs) -> str:
        result = await client.call_tool(name, kwargs)
        text = "".join(getattr(block, "text", "") for block in result.content)
        if result.is_error:  # 서버가 인자 검증 등에서 예외를 낸 경우. 도구 함수의 err() 와는 다르다
            return json.dumps({"status": "error", "code": None, "message": text, "state_after": {}})
        return text

    return StructuredTool.from_function(
        coroutine=call,
        name=name,
        description=tool.description or "",
        args_schema=tool.input_schema,
        infer_schema=False,
    )
