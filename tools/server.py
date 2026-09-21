"""MCP 도구 서버. stdio 로 실행.

    python tools/server.py

지금은 동작 확인용 도구를 손으로 등록했다.
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
from tools import media as media_tools  # noqa: E402

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


@mcp.tool(description=media_tools.SCHEMAS["set_media_action"]["description"])
def set_media_action(action: str) -> dict:
    """Control media playback: play, stop, skip forward, skip backward.
    Do not use for volume."""
    return media_tools.set_media_action(state, action)


@mcp.tool(description=media_tools.SCHEMAS["set_media_volume"]["description"])
def set_media_volume(value: int) -> dict:
    """Set the media playback volume from 0 to 100 percent.
    Do not use for playback control or vehicle alert volume."""
    return media_tools.set_media_volume(state, value)


@mcp.tool(description=media_tools.SCHEMAS["set_media_source"]["description"])
def set_media_source(source: str) -> dict:
    """Select the media source for playback. Use only for AM, FM, USB, Bluetooth,
    or internet media, not for playback actions."""
    return media_tools.set_media_source(state, source)


@mcp.tool(description=media_tools.SCHEMAS["get_media_info"]["description"])
def get_media_info(field: str) -> dict:
    """Read the album, artist, or track of the media currently playing.
    Use for media information, not for changing playback."""
    return media_tools.get_media_info(state, field)


if __name__ == "__main__":
    mcp.run()
