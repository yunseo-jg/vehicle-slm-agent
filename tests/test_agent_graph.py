from __future__ import annotations

import asyncio

from langchain_core.messages import AIMessage, HumanMessage
from mcp import Client

from agent.graph import build_graph, intent_node, make_validate_node, respond_node
from agent.mcp_tools import load_mcp_tools
from tools.server import mcp, state


def test_intent_node_detects_hvac_request():
    state = {"messages": [HumanMessage(content="에어컨 22도로")]}

    assert intent_node(state) == {"needs_tool": True}


def test_validate_applies_default_zone():
    validate = make_validate_node({"set_hvac_temperature"})
    state = {
        "tool_call": {
            "name": "set_hvac_temperature",
            "args": {"value": 22},
            "id": "call-1",
        },
        "vehicle_state": {"Vehicle.LowVoltageSystemState": "ON", "Vehicle.Speed": 0},
    }

    result = validate(state)

    assert result["tool_result"] is None
    assert result["tool_call"]["args"] == {"value": 22, "zone": "driver"}


def test_validate_asks_for_missing_temperature():
    validate = make_validate_node({"set_hvac_temperature"})
    state = {
        "tool_call": {
            "name": "set_hvac_temperature",
            "args": {"zone": "driver"},
            "id": "call-1",
        },
        "vehicle_state": {"Vehicle.LowVoltageSystemState": "ON", "Vehicle.Speed": 0},
    }

    result = validate(state)

    assert result["tool_result"]["code"] == "missing_arg"
    assert result["ask"] == "몇 도로 맞춰드릴까요?"


def test_validate_rejects_out_of_range_temperature():
    validate = make_validate_node({"set_hvac_temperature"})
    state = {
        "tool_call": {
            "name": "set_hvac_temperature",
            "args": {"value": 31, "zone": "driver"},
            "id": "call-1",
        },
        "vehicle_state": {"Vehicle.LowVoltageSystemState": "ON", "Vehicle.Speed": 0},
    }

    result = validate(state)

    assert result["tool_result"]["code"] == "out_of_range"


def test_validate_rejects_when_power_is_off():
    validate = make_validate_node({"set_hvac_temperature"})
    state = {
        "tool_call": {
            "name": "set_hvac_temperature",
            "args": {"value": 22, "zone": "driver"},
            "id": "call-1",
        },
        "vehicle_state": {"Vehicle.LowVoltageSystemState": "OFF", "Vehicle.Speed": 0},
    }

    result = validate(state)

    assert result["tool_result"]["code"] == "engine_off"


def test_respond_node_uses_error_code_message():
    state = {
        "messages": [HumanMessage(content="에어컨 40도로")],
        "needs_tool": True,
        "tool_call": None,
        "tool_result": {"status": "error", "code": "out_of_range", "state_after": {}},
    }

    result = respond_node(state)

    assert result["final_answer"] == "설정 가능한 범위를 벗어났습니다."


def test_mcp_tools_load_and_change_temperature():
    async def scenario():
        state.reset()
        try:
            async with Client(mcp, raise_exceptions=True) as client:
                tools = await load_mcp_tools(client)
                tools_by_name = {tool.name: tool for tool in tools}

                assert set(tools_by_name) == {"set_hvac_temperature", "get_vehicle_state"}
                result = await tools_by_name["set_hvac_temperature"].ainvoke(
                    {"zone": "driver", "value": 24}
                )

                assert result["status"] == "ok"
                assert (
                    result["state_after"]["Vehicle.Cabin.HVAC.Station.Row1.Driver.Temperature"]
                    == 24
                )
        finally:
            state.reset()

    asyncio.run(scenario())


def test_five_node_graph_runs_hvac_request_end_to_end():
    class FakeToolCallingModel:
        def bind_tools(self, tools):
            return self

        async def ainvoke(self, messages):
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "set_hvac_temperature",
                        "args": {"zone": "driver", "value": 22},
                        "id": "call-demo",
                        "type": "tool_call",
                    }
                ],
            )

    async def scenario():
        state.reset()
        try:
            async with Client(mcp, raise_exceptions=True) as client:
                tools = await load_mcp_tools(client)
                graph = build_graph(llm=FakeToolCallingModel(), tools=tools)
                result = await graph.ainvoke(
                    {
                        "messages": [HumanMessage(content="에어컨 22도로")],
                        "vehicle_state": state.snapshot(),
                    },
                    {"configurable": {"thread_id": "test-demo"}},
                )

                assert result["tool_call"]["name"] == "set_hvac_temperature"
                assert result["tool_result"]["status"] == "ok"
                assert result["final_answer"] == "운전석 온도를 22도로 설정했습니다."
        finally:
            state.reset()

    asyncio.run(scenario())
