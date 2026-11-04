from __future__ import annotations

import asyncio

import pytest
from mcp import Client

from sim.state import VehicleState
from tools.server import mcp
from tools.server import state as server_state
from tools.settings import (
    DOOR_INSTANCES,
    WINDOW_INSTANCES,
    set_door_lock,
    set_hazard_lights,
    set_window_position,
)

WINDOW_KEY = "Vehicle.Cabin.Door.{}.Window.Position"
DOOR_KEY = "Vehicle.Cabin.Door.{}.IsLocked"


@pytest.fixture
def state() -> VehicleState:
    return VehicleState()


def test_settings_tools_change_state(state: VehicleState):
    result = set_window_position(state, position=50, window="driver")
    assert result == {
        "status": "ok",
        "code": None,
        "state_after": {WINDOW_KEY.format(WINDOW_INSTANCES["driver"]): 50},
    }

    result = set_window_position(state, position=100, window="all")
    assert set(result["state_after"]) == {WINDOW_KEY.format(i) for i in WINDOW_INSTANCES.values()}
    assert all(v == 100 for v in result["state_after"].values())

    result = set_door_lock(state, locked=True, door="rear")
    assert result["state_after"] == {
        DOOR_KEY.format(DOOR_INSTANCES["rear_left"]): True,
        DOOR_KEY.format(DOOR_INSTANCES["rear_right"]): True,
    }
    assert state.get(DOOR_KEY.format(DOOR_INSTANCES["driver"])) is False

    result = set_hazard_lights(state, is_on=True)
    assert result["state_after"] == {"Vehicle.Body.Lights.Hazard.IsSignaling": True}


def test_window_position_rejects_out_of_range(state: VehicleState):
    result = set_window_position(state, position=150, window="driver")

    assert result["status"] == "error"
    assert result["code"] == "out_of_range"
    assert state.get(WINDOW_KEY.format(WINDOW_INSTANCES["driver"])) == 0


def test_window_refused_at_speed_80(state: VehicleState):
    state.set("Vehicle.Speed", 80)

    result = set_window_position(state, position=100, window="all")

    assert result["status"] == "error"
    assert result["code"] == "unsafe_while_driving"
    assert result["state_after"] == {}


def test_unlock_refused_while_driving(state: VehicleState):
    state.set("Vehicle.Speed", 30)

    assert set_door_lock(state, locked=True, door="all")["status"] == "ok"
    result = set_door_lock(state, locked=False, door="all")

    assert result["status"] == "error"
    assert result["code"] == "unsafe_while_driving"
    assert state.get(DOOR_KEY.format(DOOR_INSTANCES["driver"])) is True


def test_mcp_server_lists_window_enum():
    async def scenario():
        server_state.reset()
        try:
            async with Client(mcp, raise_exceptions=True) as client:
                listed = await client.list_tools()
                tools = {tool.name: tool for tool in listed.tools}
                window = tools["set_window_position"].input_schema["properties"]["window"]
                assert window["enum"] == ["all", "driver", "passenger", "rear_left", "rear_right"]
                assert window["default"] == "all"
                assert tools["set_window_position"].input_schema["required"] == ["position"]
        finally:
            server_state.reset()

    asyncio.run(scenario())
