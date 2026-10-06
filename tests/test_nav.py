from __future__ import annotations

import asyncio
import inspect
import json

import pytest
from mcp import Client

from sim.state import VehicleState
from tools.nav import (
    DESTINATION_LAT_PATH,
    DESTINATION_LON_PATH,
    MUTE_PATH,
    PLACES,
    SCHEMAS,
    VOLUME_PATH,
    get_nav_location,
    set_nav_destination,
    set_nav_mute,
    set_nav_volume,
)
from tools.server import mcp
from tools.server import state as server_state


@pytest.fixture
def state() -> VehicleState:
    return VehicleState()


# set_nav_mute
@pytest.mark.parametrize("mute_state", ["MUTED", "ALERT_ONLY", "UNMUTED"])
def test_set_nav_mute(state: VehicleState, mute_state: str):
    result = set_nav_mute(state, mute_state)

    assert result == {"status": "ok", "code": None, "state_after": {MUTE_PATH: mute_state}}
    assert state.get(MUTE_PATH) == mute_state


def test_set_nav_mute_rejects_unknown_value(state: VehicleState):
    result = set_nav_mute(state, "OFF")

    assert result["status"] == "error"
    assert result["code"] == "out_of_range"


# set_nav_volume
@pytest.mark.parametrize("value", [0, 30, 100])
def test_set_nav_volume(state: VehicleState, value: int):
    result = set_nav_volume(state, value)

    assert result["status"] == "ok"
    assert result["state_after"] == {VOLUME_PATH: value}


@pytest.mark.parametrize("value", [-1, 101, True])
def test_set_nav_volume_rejects_out_of_range(state: VehicleState, value):
    result = set_nav_volume(state, value)

    assert result["code"] == "out_of_range"


# get_nav_location
def test_get_nav_location(state: VehicleState):
    result = get_nav_location(state, "latitude")

    assert result["status"] == "ok"
    assert result["state_after"] == {"Vehicle.CurrentLocation.Latitude": 37.5665}


def test_get_nav_location_rejects_unknown_field(state: VehicleState):
    result = get_nav_location(state, "altitude")

    assert result["code"] == "out_of_range"


# set_nav_destination
def test_set_nav_destination(state: VehicleState):
    result = set_nav_destination(state, "회사")

    latitude, longitude = PLACES["회사"]
    assert result == {
        "status": "ok",
        "code": None,
        "state_after": {DESTINATION_LAT_PATH: latitude, DESTINATION_LON_PATH: longitude},
    }
    assert state.get(DESTINATION_LAT_PATH) == latitude
    assert state.get(DESTINATION_LON_PATH) == longitude


def test_set_nav_destination_strips_whitespace(state: VehicleState):
    result = set_nav_destination(state, " 집 ")

    assert result["status"] == "ok"


def test_set_nav_destination_unknown_place(state: VehicleState):
    result = set_nav_destination(state, "안암역")

    assert result["status"] == "error"
    assert result["code"] == "not_found"
    assert state.get(DESTINATION_LAT_PATH) is None


@pytest.mark.parametrize("place_name", ["", "   "])
def test_set_nav_destination_empty_name(state: VehicleState, place_name: str):
    result = set_nav_destination(state, place_name)

    assert result["code"] == "missing_arg"


# 공통: 시동 꺼짐
@pytest.mark.parametrize(
    ("tool", "args"),
    [
        (set_nav_mute, ("MUTED",)),
        (set_nav_volume, (40,)),
        (set_nav_destination, ("집",)),
    ],
)
def test_nav_set_tools_require_power(state: VehicleState, tool, args):
    state.set("Vehicle.LowVoltageSystemState", "OFF")

    result = tool(state, *args)

    assert result["status"] == "error"
    assert result["code"] == "engine_off"


def test_get_nav_location_works_without_power(state: VehicleState):
    # get_nav_location 은 precondition 이 없다 (온톨로지 정의)
    state.set("Vehicle.LowVoltageSystemState", "OFF")

    result = get_nav_location(state, "longitude")

    assert result["status"] == "ok"


def test_nav_tool_descriptions_match_generated_schema():
    functions = {
        "set_nav_mute": set_nav_mute,
        "set_nav_volume": set_nav_volume,
        "get_nav_location": get_nav_location,
        "set_nav_destination": set_nav_destination,
    }

    assert set(functions) == set(SCHEMAS)
    for name, function in functions.items():
        description = " ".join(inspect.getdoc(function).split())
        assert description == SCHEMAS[name]["description"]


def test_mcp_server_exposes_and_runs_nav_tools():
    async def scenario():
        server_state.reset()
        try:
            async with Client(mcp, raise_exceptions=True) as client:
                listed = await client.list_tools()
                listed_by_name = {tool.name: tool for tool in listed.tools}
                assert set(SCHEMAS) <= set(listed_by_name)
                for name, schema in SCHEMAS.items():
                    assert listed_by_name[name].description == schema["description"]

                result = await client.call_tool("set_nav_destination", {"place_name": "서울역"})
                text = "".join(getattr(block, "text", "") for block in result.content)
                payload = json.loads(text)
                latitude, longitude = PLACES["서울역"]
                assert payload["status"] == "ok"
                assert payload["state_after"] == {
                    DESTINATION_LAT_PATH: latitude,
                    DESTINATION_LON_PATH: longitude,
                }

                result = await client.call_tool("set_nav_mute", {"state": "MUTED"})
                text = "".join(getattr(block, "text", "") for block in result.content)
                assert json.loads(text)["state_after"] == {MUTE_PATH: "MUTED"}
        finally:
            server_state.reset()

    asyncio.run(scenario())
