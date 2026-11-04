"""차량설정 도메인 도구 구현."""

from __future__ import annotations

import json
from pathlib import Path

from ontology.build_schema import load_ontology
from sim.state import PreconditionError, VehicleState, err, ok

ROOT = Path(__file__).resolve().parent.parent
TOOLS_SCHEMA = ROOT / "ontology" / "generated" / "tools.json"


def _load_settings_schemas() -> dict[str, dict]:
    with TOOLS_SCHEMA.open(encoding="utf-8") as file:
        tools = json.load(file)
    return {tool["name"]: tool for tool in tools if tool["domain"] == "settings"}


SCHEMAS = _load_settings_schemas()
WINDOW_SCHEMA = SCHEMAS["set_window_position"]
DOOR_SCHEMA = SCHEMAS["set_door_lock"]
HAZARD_SCHEMA = SCHEMAS["set_hazard_lights"]
HORN_SCHEMA = SCHEMAS["set_horn"]

# 파라미터 값(driver, rear_left ...) → VSS instance 이름.
# all / rear 는 _expand 에서 여러 개로 펼친다
INSTANCE_MAP = load_ontology()["instance_map"]
WINDOW_INSTANCES = INSTANCE_MAP["window"]
DOOR_INSTANCES = INSTANCE_MAP["door"]

WINDOW_PATH = WINDOW_SCHEMA["vss"]
DOOR_PATH = DOOR_SCHEMA["vss"]
HAZARD_PATH = HAZARD_SCHEMA["vss"]
HORN_PATH = HORN_SCHEMA["vss"]

WINDOWS = frozenset(WINDOW_SCHEMA["parameters"]["properties"]["window"]["enum"])
DOORS = frozenset(DOOR_SCHEMA["parameters"]["properties"]["door"]["enum"])
POSITION_RULE = WINDOW_SCHEMA["parameters"]["properties"]["position"]


def _check_preconditions(state: VehicleState, schema: dict) -> dict | None:
    try:
        state.check(schema["precondition"])
    except PreconditionError as error:
        return err(error.code, str(error))
    return None


def _expand(template: str, token: str, selected: str, instances: dict[str, str]) -> list[str]:
    """선택값 하나를 VSS 경로 목록으로. all 은 전부, rear 는 rear_* 전부, 나머지는 하나."""
    if selected == "all":
        names = list(instances)
    elif selected == "rear":
        names = [name for name in instances if name.startswith("rear")]
    else:
        names = [selected]
    return [template.replace("{" + token + "}", instances[name]) for name in names]


def _is_bool(value: object) -> bool:
    return isinstance(value, bool)


def set_window_position(state: VehicleState, position: int, window: str = "all") -> dict:
    """Open or close windows to a position (0 closed, 100 fully open). Use for any request
    to open, close, lower, or raise a window. Do not use for doors or the sunroof."""
    if window not in WINDOWS:
        return err("out_of_range", f"window must be one of {sorted(WINDOWS)}")
    minimum = POSITION_RULE["minimum"]
    maximum = POSITION_RULE["maximum"]
    if not isinstance(position, int) or _is_bool(position) or not minimum <= position <= maximum:
        return err("out_of_range", f"position must be an integer from {minimum} to {maximum}")
    if error := _check_preconditions(state, WINDOW_SCHEMA):
        return error
    changed = {}
    for key in _expand(WINDOW_PATH, "window", window, WINDOW_INSTANCES):
        state.set(key, position)
        changed[key] = position
    return ok(state, changed)


def set_door_lock(state: VehicleState, locked: bool, door: str = "all") -> dict:
    """Lock or unlock doors. Use when the user asks to lock, unlock, open, or close a car door.
    Do not use for windows or the trunk."""
    if door not in DOORS:
        return err("out_of_range", f"door must be one of {sorted(DOORS)}")
    if not _is_bool(locked):
        return err("out_of_range", "locked must be true or false")
    if error := _check_preconditions(state, DOOR_SCHEMA):
        return error
    # 잠금은 주행 중에도 되지만 해제는 정차 중에만. precondition 은 인자별로 못 걸어서 여기서 검사
    if not locked:
        try:
            state.check(["parked"])
        except PreconditionError:
            return err("unsafe_while_driving", "cannot unlock doors while driving")
    changed = {}
    for key in _expand(DOOR_PATH, "door", door, DOOR_INSTANCES):
        state.set(key, locked)
        changed[key] = locked
    return ok(state, changed)


def set_hazard_lights(state: VehicleState, is_on: bool) -> dict:
    """Turn the hazard warning lights on or off. Use when the user mentions hazard lights or
    an emergency stop signal. Do not use for headlights or turn signals."""
    if not _is_bool(is_on):
        return err("out_of_range", "is_on must be true or false")
    if error := _check_preconditions(state, HAZARD_SCHEMA):
        return error
    state.set(HAZARD_PATH, is_on)
    return ok(state, {HAZARD_PATH: is_on})


def set_horn(state: VehicleState, is_active: bool) -> dict:
    """Sound or stop the horn. Use when the user asks to honk or press the horn.
    Do not use for hazard lights or any other sound."""
    if not _is_bool(is_active):
        return err("out_of_range", "is_active must be true or false")
    if error := _check_preconditions(state, HORN_SCHEMA):
        return error
    state.set(HORN_PATH, is_active)
    return ok(state, {HORN_PATH: is_active})


# 도구 이름 → 구현. tools/server.py 가 tools.json 의 도구를 여기서 찾아 등록한다
HANDLERS = {
    "set_window_position": set_window_position,
    "set_door_lock": set_door_lock,
    "set_hazard_lights": set_hazard_lights,
    "set_horn": set_horn,
}
