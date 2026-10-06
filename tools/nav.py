"""내비게이션 도메인 도구 구현."""

from __future__ import annotations

import json
from pathlib import Path

from sim.state import PreconditionError, VehicleState, err, ok

ROOT = Path(__file__).resolve().parent.parent
TOOLS_SCHEMA = ROOT / "ontology" / "generated" / "tools.json"

# 장소명 → (위도, 경도). 실제 지오코딩 대신 쓰는 팀 자체 사전 (오프라인 전제).
# 집·회사는 데모용 가상 좌표, 나머지는 대략적인 실제 좌표.
PLACES: dict[str, tuple[float, float]] = {
    "집": (37.5400, 127.0700),
    "회사": (37.5660, 126.9780),
    "학교": (37.5895, 127.0323),
    "서울역": (37.5547, 126.9707),
    "강남역": (37.4979, 127.0276),
}


def _load_nav_schemas() -> dict[str, dict]:
    with TOOLS_SCHEMA.open(encoding="utf-8") as file:
        tools = json.load(file)
    return {tool["name"]: tool for tool in tools if tool["domain"] == "nav"}


SCHEMAS = _load_nav_schemas()
MUTE_SCHEMA = SCHEMAS["set_nav_mute"]
VOLUME_SCHEMA = SCHEMAS["set_nav_volume"]
LOCATION_SCHEMA = SCHEMAS["get_nav_location"]
DESTINATION_SCHEMA = SCHEMAS["set_nav_destination"]

MUTE_PATH = MUTE_SCHEMA["vss"]
VOLUME_PATH = VOLUME_SCHEMA["vss"]
LOCATION_FIELDS = LOCATION_SCHEMA["vss"]
DESTINATION_LAT_PATH = DESTINATION_SCHEMA["vss"]["latitude"]
DESTINATION_LON_PATH = DESTINATION_SCHEMA["vss"]["longitude"]

MUTE_STATES = frozenset(MUTE_SCHEMA["parameters"]["properties"]["state"]["enum"])
VOLUME_RULE = VOLUME_SCHEMA["parameters"]["properties"]["value"]


def _check_preconditions(state: VehicleState, schema: dict) -> dict | None:
    try:
        state.check(schema["precondition"])
    except PreconditionError as error:
        return err(error.code, str(error))
    return None


def set_nav_mute(state: VehicleState, mute_state: str) -> dict:
    """Mute or unmute the navigation voice guidance. Use when the user wants to
    silence or restore turn-by-turn spoken directions. Do not use for media or overall volume."""
    if mute_state not in MUTE_STATES:
        return err("out_of_range", f"state must be one of {sorted(MUTE_STATES)}")
    if error := _check_preconditions(state, MUTE_SCHEMA):
        return error
    state.set(MUTE_PATH, mute_state)
    return ok(state, {MUTE_PATH: mute_state})


def set_nav_volume(state: VehicleState, value: int) -> dict:
    """Set the navigation voice guidance volume (0-100 percent). Use for how loud the
    route guidance speaks. Do not use for media volume or muting."""
    minimum = VOLUME_RULE["minimum"]
    maximum = VOLUME_RULE["maximum"]
    if not isinstance(value, int) or isinstance(value, bool) or not minimum <= value <= maximum:
        return err("out_of_range", f"value must be an integer from {minimum} to {maximum}")
    if error := _check_preconditions(state, VOLUME_SCHEMA):
        return error
    state.set(VOLUME_PATH, value)
    return ok(state, {VOLUME_PATH: value})


def get_nav_location(state: VehicleState, field: str) -> dict:
    """Read the vehicle's current location coordinate (latitude or longitude).
    Use for questions about where the car is now. Not for setting a destination."""
    if field not in LOCATION_FIELDS:
        return err("out_of_range", f"field must be one of {sorted(LOCATION_FIELDS)}")
    if error := _check_preconditions(state, LOCATION_SCHEMA):
        return error
    key = LOCATION_FIELDS[field]
    return ok(state, {key: state.get(key)})


def set_nav_destination(state: VehicleState, place_name: str) -> dict:
    """Set the navigation destination by place name. Pass the Korean place name exactly as the
    user said it, without particles such as 으로 or 까지.
    Do not use for guidance volume or muting."""
    if not isinstance(place_name, str) or not place_name.strip():
        return err("missing_arg", "place_name is required")
    name = place_name.strip()
    if name not in PLACES:
        return err("not_found", f"unknown place: {name}")
    if error := _check_preconditions(state, DESTINATION_SCHEMA):
        return error
    latitude, longitude = PLACES[name]
    state.set(DESTINATION_LAT_PATH, latitude)
    state.set(DESTINATION_LON_PATH, longitude)
    return ok(state, {DESTINATION_LAT_PATH: latitude, DESTINATION_LON_PATH: longitude})
