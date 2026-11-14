"""공조 도메인 도구 구현."""

from __future__ import annotations

import json
from pathlib import Path

from ontology.build_schema import load_ontology
from sim.state import PreconditionError, VehicleState, err, ok

ROOT = Path(__file__).resolve().parent.parent
TOOLS_SCHEMA = ROOT / "ontology" / "generated" / "tools.json"


def _load_hvac_schemas() -> dict[str, dict]:
    with TOOLS_SCHEMA.open(encoding="utf-8") as file:
        tools = json.load(file)
    return {tool["name"]: tool for tool in tools if tool["domain"] == "hvac"}


SCHEMAS = _load_hvac_schemas()

# 파라미터 값(driver, rear_left ...) → VSS instance 이름. tools.json 에는 없어서 온톨로지에서 읽는다
INSTANCE_MAP = load_ontology()["instance_map"]
TEMPERATURE_SCHEMA = SCHEMAS["set_hvac_temperature"]
FAN_SPEED_SCHEMA = SCHEMAS["set_hvac_fan_speed"]
AC_POWER_SCHEMA = SCHEMAS["set_hvac_ac_power"]
DEFROSTER_SCHEMA = SCHEMAS["set_hvac_defroster"]
SEAT_HEATING_SCHEMA = SCHEMAS["set_hvac_seat_heating"]

AC_POWER_PATH = AC_POWER_SCHEMA["vss"]
DEFROSTER_PATH = DEFROSTER_SCHEMA["vss"]

ZONES = INSTANCE_MAP["zone"]
SEATS = INSTANCE_MAP["seat"]


def _check_preconditions(state: VehicleState, schema: dict) -> dict | None:
    try:
        state.check(schema["precondition"])
    except PreconditionError as error:
        return err(error.code, str(error))
    return None


def _check_enum(schema: dict, name: str, value: object) -> dict | None:
    allowed = schema["parameters"]["properties"][name]["enum"]
    if value not in allowed:
        return err("out_of_range", f"{name} must be one of {allowed}")
    return None


def _check_int(schema: dict, name: str, value: object) -> dict | None:
    rule = schema["parameters"]["properties"][name]
    minimum = rule["minimum"]
    maximum = rule["maximum"]
    if not isinstance(value, int) or isinstance(value, bool) or not minimum <= value <= maximum:
        return err("out_of_range", f"{name} must be an integer from {minimum} to {maximum}")
    return None


def _check_bool(name: str, value: object) -> dict | None:
    if not isinstance(value, bool):
        return err("out_of_range", f"{name} must be true or false")
    return None


def set_hvac_temperature(state: VehicleState, value: int, zone: str = "driver") -> dict:
    """Set the cabin temperature for one seat zone. Use when the user asks to change,
    raise, or lower the temperature. Do not use for fan speed or turning A/C on/off."""
    if error := _check_enum(TEMPERATURE_SCHEMA, "zone", zone):
        return error
    if error := _check_int(TEMPERATURE_SCHEMA, "value", value):
        return error
    if error := _check_preconditions(state, TEMPERATURE_SCHEMA):
        return error
    path = TEMPERATURE_SCHEMA["vss"].format(zone=ZONES[zone])
    state.set(path, value)
    return ok(state, {path: value})


def set_hvac_fan_speed(state: VehicleState, value: int, zone: str = "driver") -> dict:
    """Set fan speed (0-100 percent) for one seat zone. Use for wind strength requests.
    Do not use for temperature."""
    if error := _check_enum(FAN_SPEED_SCHEMA, "zone", zone):
        return error
    if error := _check_int(FAN_SPEED_SCHEMA, "value", value):
        return error
    if error := _check_preconditions(state, FAN_SPEED_SCHEMA):
        return error
    path = FAN_SPEED_SCHEMA["vss"].format(zone=ZONES[zone])
    state.set(path, value)
    return ok(state, {path: value})


def set_hvac_ac_power(state: VehicleState, enabled: bool) -> dict:
    """Turn the air conditioner on or off. Use when the user asks to turn the A/C on or off.
    Do not use for temperature or fan speed."""
    if error := _check_bool("enabled", enabled):
        return error
    if error := _check_preconditions(state, AC_POWER_SCHEMA):
        return error
    state.set(AC_POWER_PATH, enabled)
    return ok(state, {AC_POWER_PATH: enabled})


def set_hvac_defroster(state: VehicleState, enabled: bool) -> dict:
    """Turn the front windshield defroster on or off. Use when the windshield is fogged or frosted.
    Do not use for temperature or the air conditioner."""
    if error := _check_bool("enabled", enabled):
        return error
    if error := _check_preconditions(state, DEFROSTER_SCHEMA):
        return error
    state.set(DEFROSTER_PATH, enabled)
    return ok(state, {DEFROSTER_PATH: enabled})


def set_hvac_seat_heating(state: VehicleState, value: int, seat: str = "driver") -> dict:
    """Set seat heater level (0 off, 100 maximum) for one seat.
    Use when the user asks for a heated or warm seat. Do not use for cabin temperature."""
    if error := _check_enum(SEAT_HEATING_SCHEMA, "seat", seat):
        return error
    if error := _check_int(SEAT_HEATING_SCHEMA, "value", value):
        return error
    if error := _check_preconditions(state, SEAT_HEATING_SCHEMA):
        return error
    path = SEAT_HEATING_SCHEMA["vss"].format(seat=SEATS[seat])
    state.set(path, value)
    return ok(state, {path: value})


# 도구 이름 → 구현. tools/server.py 가 tools.json 의 도구를 여기서 찾아 등록한다
HANDLERS = {
    "set_hvac_temperature": set_hvac_temperature,
    "set_hvac_fan_speed": set_hvac_fan_speed,
    "set_hvac_ac_power": set_hvac_ac_power,
    "set_hvac_defroster": set_hvac_defroster,
    "set_hvac_seat_heating": set_hvac_seat_heating,
}
