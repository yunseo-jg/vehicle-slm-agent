from __future__ import annotations

import asyncio
import inspect
import json

import pytest
from mcp import Client

from sim.state import VehicleState
from tools.media import (
    ACTION_PATH,
    SCHEMAS,
    SOURCE_PATH,
    VOLUME_PATH,
    get_media_info,
    set_media_action,
    set_media_source,
    set_media_volume,
)
from tools.server import mcp
from tools.server import state as server_state


@pytest.fixture
def state() -> VehicleState:
    return VehicleState()


@pytest.mark.parametrize("action", ["PLAY", "STOP", "SKIP_FORWARD", "SKIP_BACKWARD"])
def test_set_media_action(state: VehicleState, action: str):
    result = set_media_action(state, action)

    assert result == {"status": "ok", "code": None, "state_after": {ACTION_PATH: action}}
    assert state.get(ACTION_PATH) == action


def test_set_media_action_rejects_unknown_value(state: VehicleState):
    result = set_media_action(state, "PAUSE")

    assert result["status"] == "error"
    assert result["code"] == "out_of_range"


@pytest.mark.parametrize("value", [0, 40, 100])
def test_set_media_volume(state: VehicleState, value: int):
    result = set_media_volume(state, value)

    assert result["status"] == "ok"
    assert result["state_after"] == {VOLUME_PATH: value}


@pytest.mark.parametrize("value", [-1, 101, True])
def test_set_media_volume_rejects_out_of_range(state: VehicleState, value):
    result = set_media_volume(state, value)

    assert result["code"] == "out_of_range"


@pytest.mark.parametrize("source", ["AM", "FM", "USB", "BLUETOOTH", "INTERNET"])
def test_set_media_source(state: VehicleState, source: str):
    result = set_media_source(state, source)

    assert result["status"] == "ok"
    assert result["state_after"] == {SOURCE_PATH: source}


def test_get_media_info(state: VehicleState):
    result = get_media_info(state, "track")

    assert result["status"] == "ok"
    assert result["state_after"] == {"Vehicle.Cabin.Infotainment.Media.Played.Track": "Demo Track"}


@pytest.mark.parametrize(
    ("tool", "args"),
    [
        (set_media_action, ("PLAY",)),
        (set_media_volume, (40,)),
        (set_media_source, ("FM",)),
        (get_media_info, ("track",)),
    ],
)
def test_media_tools_require_power(state: VehicleState, tool, args):
    state.set("Vehicle.LowVoltageSystemState", "OFF")

    result = tool(state, *args)

    assert result["status"] == "error"
    assert result["code"] == "engine_off"


def test_media_tool_descriptions_match_generated_schema():
    functions = {
        "set_media_action": set_media_action,
        "set_media_volume": set_media_volume,
        "set_media_source": set_media_source,
        "get_media_info": get_media_info,
    }

    for name, function in functions.items():
        description = " ".join(inspect.getdoc(function).split())
        assert description == SCHEMAS[name]["description"]


def test_mcp_server_exposes_and_runs_media_tools():
    async def scenario():
        server_state.reset()
        try:
            async with Client(mcp, raise_exceptions=True) as client:
                listed = await client.list_tools()
                names = {tool.name for tool in listed.tools}
                assert {
                    "set_media_action",
                    "set_media_volume",
                    "set_media_source",
                    "get_media_info",
                } <= names
                listed_by_name = {tool.name: tool for tool in listed.tools}
                for name, schema in SCHEMAS.items():
                    assert listed_by_name[name].description == schema["description"]

                result = await client.call_tool("set_media_action", {"action": "PLAY"})
                text = "".join(getattr(block, "text", "") for block in result.content)
                payload = json.loads(text)
                assert payload["status"] == "ok"
                assert payload["state_after"] == {ACTION_PATH: "PLAY"}
        finally:
            server_state.reset()

    asyncio.run(scenario())
