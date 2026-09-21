"""'에어컨 22도로' 최소 그래프 데모."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402
from langchain_core.messages import HumanMessage  # noqa: E402
from langchain_openai import ChatOpenAI  # noqa: E402
from mcp import Client, StdioServerParameters  # noqa: E402

from agent.graph import build_graph  # noqa: E402
from agent.mcp_tools import load_mcp_tools  # noqa: E402

INITIAL_STATE = ROOT / "ontology" / "generated" / "initial_state.json"


async def main() -> None:
    load_dotenv(ROOT / ".env")
    model_name = os.environ.get("OPENAI_MODEL")
    if not model_name:
        raise RuntimeError(".env에 OPENAI_MODEL을 지정하세요.")

    llm = ChatOpenAI(
        model=model_name,
        temperature=0,
        reasoning_effort="none",
    )
    server = StdioServerParameters(
        command=sys.executable,
        args=[str(ROOT / "tools" / "server.py")],
        cwd=ROOT,
    )

    with INITIAL_STATE.open(encoding="utf-8") as file:
        vehicle_state = json.load(file)

    async with Client(server) as client:
        tools = await load_mcp_tools(client)
        tools_by_name = {tool.name: tool for tool in tools}

        await tools_by_name["set_hvac_temperature"].ainvoke({"zone": "driver", "value": 24})
        vehicle_state["Vehicle.Cabin.HVAC.Station.Row1.Driver.Temperature"] = 24

        graph = build_graph(llm=llm, tools=tools)
        result = await graph.ainvoke(
            {
                "messages": [HumanMessage(content="에어컨 22도로")],
                "vehicle_state": vehicle_state,
            },
            {"configurable": {"thread_id": "demo-1"}},
        )

        print("tool_call:", result["tool_call"])
        print("tool_result:", result["tool_result"])
        print("final_answer:", result["final_answer"])
        print("\nMermaid diagram:\n", graph.get_graph().draw_mermaid())


if __name__ == "__main__":
    asyncio.run(main())
