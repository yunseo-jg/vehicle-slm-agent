"""상태 조회 도메인 도구 구현."""

from __future__ import annotations

import json
from pathlib import Path

from sim.state import PreconditionError, VehicleState, err, ok

ROOT = Path(__file__).resolve().parent.parent
TOOLS_SCHEMA = ROOT / "ontology" / "generated" / "tools.json"


def _load_status_schemas() -> dict[str, dict]:
    with TOOLS_SCHEMA.open(encoding="utf-8") as file:
        tools = json.load(file)
    return {tool["name"]: tool for tool in tools if tool["domain"] == "status"}


SCHEMAS = _load_status_schemas()
STATE_SCHEMA = SCHEMAS["get_vehicle_state"]

STATE_FIELDS = STATE_SCHEMA["vss"]


def _check_preconditions(state: VehicleState, schema: dict) -> dict | None:
    try:
        state.check(schema["precondition"])
    except PreconditionError as error:
        return err(error.code, str(error))
    return None


def get_vehicle_state(state: VehicleState, field: str) -> dict:
    """Read a vehicle status value such as battery level, range, or speed.
    Use for questions, not for changing anything."""
    if field not in STATE_FIELDS:
        return err("out_of_range", f"field must be one of {sorted(STATE_FIELDS)}")
    if error := _check_preconditions(state, STATE_SCHEMA):
        return error
    key = STATE_FIELDS[field]
    return ok(state, {key: state.get(key)})


# 도구 이름 → 구현. tools/server.py 가 tools.json 의 도구를 여기서 찾아 등록한다
HANDLERS = {
    "get_vehicle_state": get_vehicle_state,
}
