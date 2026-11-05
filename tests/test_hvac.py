from __future__ import annotations

import inspect

import pytest

from sim.state import VehicleState
from tools.hvac import (
    AC_POWER_PATH,
    DEFROSTER_PATH,
    HANDLERS,
    SCHEMAS,
    set_hvac_ac_power,
    set_hvac_defroster,
    set_hvac_fan_speed,
    set_hvac_seat_heating,
    set_hvac_temperature,
)

STATION = "Vehicle.Cabin.HVAC.Station"
SEAT = "Vehicle.Cabin.Seat"


@pytest.fixture
def state() -> VehicleState:
    return VehicleState()


@pytest.mark.parametrize(
    ("zone", "instance"),
    [("driver", "Row1.Driver"), ("passenger", "Row1.Passenger"), ("rear", "Row2.Driver")],
)
def test_set_hvac_temperature(state: VehicleState, zone: str, instance: str):
    result = set_hvac_temperature(state, 25, zone)

    key = f"{STATION}.{instance}.Temperature"
    assert result == {"status": "ok", "code": None, "state_after": {key: 25}}
    assert state.get(key) == 25


def test_set_hvac_temperature_defaults_to_driver(state: VehicleState):
    result = set_hvac_temperature(state, 20)

    assert result["state_after"] == {f"{STATION}.Row1.Driver.Temperature": 20}


@pytest.mark.parametrize("value", [15, 31, True])
def test_set_hvac_temperature_rejects_out_of_range(state: VehicleState, value):
    result = set_hvac_temperature(state, value)

    assert result["status"] == "error"
    assert result["code"] == "out_of_range"


def test_set_hvac_temperature_rejects_unknown_zone(state: VehicleState):
    result = set_hvac_temperature(state, 22, "rear_left")

    assert result["code"] == "out_of_range"


@pytest.mark.parametrize("value", [0, 50, 100])
def test_set_hvac_fan_speed(state: VehicleState, value: int):
    result = set_hvac_fan_speed(state, value, "passenger")

    assert result["status"] == "ok"
    assert result["state_after"] == {f"{STATION}.Row1.Passenger.FanSpeed": value}


@pytest.mark.parametrize("value", [-1, 101, True])
def test_set_hvac_fan_speed_rejects_out_of_range(state: VehicleState, value):
    result = set_hvac_fan_speed(state, value)

    assert result["code"] == "out_of_range"


@pytest.mark.parametrize("enabled", [True, False])
def test_set_hvac_ac_power(state: VehicleState, enabled: bool):
    result = set_hvac_ac_power(state, enabled)

    assert result["status"] == "ok"
    assert result["state_after"] == {AC_POWER_PATH: enabled}
    assert state.get(AC_POWER_PATH) is enabled


@pytest.mark.parametrize("enabled", ["ON", 1, None])
def test_set_hvac_ac_power_rejects_non_bool(state: VehicleState, enabled):
    result = set_hvac_ac_power(state, enabled)

    assert result["code"] == "out_of_range"


@pytest.mark.parametrize("enabled", [True, False])
def test_set_hvac_defroster(state: VehicleState, enabled: bool):
    result = set_hvac_defroster(state, enabled)

    assert result["status"] == "ok"
    assert result["state_after"] == {DEFROSTER_PATH: enabled}


@pytest.mark.parametrize("enabled", ["OFF", 0])
def test_set_hvac_defroster_rejects_non_bool(state: VehicleState, enabled):
    result = set_hvac_defroster(state, enabled)

    assert result["code"] == "out_of_range"


@pytest.mark.parametrize(
    ("seat", "instance"),
    [
        ("driver", "Row1.DriverSide"),
        ("passenger", "Row1.PassengerSide"),
        ("rear_left", "Row2.DriverSide"),
        ("rear_right", "Row2.PassengerSide"),
    ],
)
def test_set_hvac_seat_heating(state: VehicleState, seat: str, instance: str):
    result = set_hvac_seat_heating(state, 100, seat)

    assert result["status"] == "ok"
    assert result["state_after"] == {f"{SEAT}.{instance}.HeatingCooling": 100}


@pytest.mark.parametrize("value", [-1, 101, True])
def test_set_hvac_seat_heating_rejects_out_of_range(state: VehicleState, value):
    result = set_hvac_seat_heating(state, value)

    assert result["code"] == "out_of_range"


def test_set_hvac_seat_heating_rejects_unknown_seat(state: VehicleState):
    result = set_hvac_seat_heating(state, 50, "rear")

    assert result["code"] == "out_of_range"


@pytest.mark.parametrize(
    ("tool", "args"),
    [
        (set_hvac_temperature, (22,)),
        (set_hvac_fan_speed, (40,)),
        (set_hvac_ac_power, (True,)),
        (set_hvac_defroster, (True,)),
        (set_hvac_seat_heating, (50,)),
    ],
)
def test_hvac_tools_require_power(state: VehicleState, tool, args):
    state.set("Vehicle.LowVoltageSystemState", "OFF")
    before = state.snapshot()

    result = tool(state, *args)

    assert result["status"] == "error"
    assert result["code"] == "engine_off"
    assert state.snapshot() == before


def test_hvac_handlers_cover_all_schemas():
    assert set(HANDLERS) == set(SCHEMAS)


def test_hvac_tool_descriptions_match_generated_schema():
    for name, function in HANDLERS.items():
        description = " ".join(inspect.getdoc(function).split())
        assert description == SCHEMAS[name]["description"]
