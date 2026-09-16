"""MCP 도구 서버. stdio 로 실행.

    python tools/server.py

지금은 동작 확인용으로 도구 2개만 손으로 등록했다.
4주차에 ontology/generated/tools.json 을 읽어 도메인별 구현(tools/<domain>.py)과
묶는 방식으로 바꾼다.
반환 형식은 sim.state.ok / err 만 쓴다.

MCP Python SDK 2.x 기준 (FastMCP 가 MCPServer 로 이름이 바뀜). 1.x 예제를 따라 하지 않는다.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mcp.server.mcpserver import MCPServer  # noqa: E402

from sim.state import PreconditionError, VehicleState, err, ok  # noqa: E402

mcp = MCPServer("vehicle")
state = VehicleState()

ZONE = {"driver": "Row1.Driver", "passenger": "Row1.Passenger", "rear": "Row2.Driver"}


@mcp.tool()
def set_hvac_temperature(value: int, zone: str = "driver") -> dict:
    """Set the cabin temperature for one seat zone. Use when the user asks to change,
    raise, or lower the temperature. Do not use for fan speed or turning A/C on/off."""
    if zone not in ZONE:
        return err("out_of_range", f"zone must be one of {list(ZONE)}")
    if not 16 <= value <= 30:
        return err("out_of_range", "value must be 16-30")
    try:
        state.check(["power_on"])
    except PreconditionError as e:
        return err(e.code, str(e))
    key = f"Vehicle.Cabin.HVAC.Station.{ZONE[zone]}.Temperature"
    state.set(key, value)
    return ok(state, {key: value})


@mcp.tool()
def get_vehicle_state(field: str) -> dict:
    """Read a vehicle status value such as battery level, range, or speed.
    Use for questions, not for changing anything."""
    fields = {
        "battery": "Vehicle.Powertrain.TractionBattery.StateOfCharge.Displayed",
        "range": "Vehicle.Powertrain.Range",
        "speed": "Vehicle.Speed",
    }
    if field not in fields:
        return err("out_of_range", f"field must be one of {list(fields)}")
    key = fields[field]
    return ok(state, {key: state.get(key)})


if __name__ == "__main__":
    mcp.run()
