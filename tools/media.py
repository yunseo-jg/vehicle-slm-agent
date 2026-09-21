"""미디어 도메인 도구 구현."""

from __future__ import annotations

import json
from pathlib import Path

from sim.state import PreconditionError, VehicleState, err, ok

ROOT = Path(__file__).resolve().parent.parent
TOOLS_SCHEMA = ROOT / "ontology" / "generated" / "tools.json"


def _load_media_schemas() -> dict[str, dict]:
    with TOOLS_SCHEMA.open(encoding="utf-8") as file:
        tools = json.load(file)
    return {tool["name"]: tool for tool in tools if tool["domain"] == "media"}


SCHEMAS = _load_media_schemas()
ACTION_SCHEMA = SCHEMAS["set_media_action"]
VOLUME_SCHEMA = SCHEMAS["set_media_volume"]
SOURCE_SCHEMA = SCHEMAS["set_media_source"]
INFO_SCHEMA = SCHEMAS["get_media_info"]

ACTION_PATH = ACTION_SCHEMA["vss"]
VOLUME_PATH = VOLUME_SCHEMA["vss"]
SOURCE_PATH = SOURCE_SCHEMA["vss"]
INFO_FIELDS = INFO_SCHEMA["vss"]

ACTIONS = frozenset(ACTION_SCHEMA["parameters"]["properties"]["action"]["enum"])
SOURCES = frozenset(SOURCE_SCHEMA["parameters"]["properties"]["source"]["enum"])
VOLUME_RULE = VOLUME_SCHEMA["parameters"]["properties"]["value"]


def _check_preconditions(state: VehicleState, schema: dict) -> dict | None:
    try:
        state.check(schema["precondition"])
    except PreconditionError as error:
        return err(error.code, str(error))
    return None


def set_media_action(state: VehicleState, action: str) -> dict:
    """Control media playback: play, stop, skip forward, skip backward.
    Do not use for volume."""
    if action not in ACTIONS:
        return err("out_of_range", f"action must be one of {sorted(ACTIONS)}")
    if error := _check_preconditions(state, ACTION_SCHEMA):
        return error
    state.set(ACTION_PATH, action)
    return ok(state, {ACTION_PATH: action})


def set_media_volume(state: VehicleState, value: int) -> dict:
    """Set the media playback volume from 0 to 100 percent.
    Do not use for playback control or vehicle alert volume."""
    minimum = VOLUME_RULE["minimum"]
    maximum = VOLUME_RULE["maximum"]
    if not isinstance(value, int) or isinstance(value, bool) or not minimum <= value <= maximum:
        return err("out_of_range", f"value must be an integer from {minimum} to {maximum}")
    if error := _check_preconditions(state, VOLUME_SCHEMA):
        return error
    state.set(VOLUME_PATH, value)
    return ok(state, {VOLUME_PATH: value})


def set_media_source(state: VehicleState, source: str) -> dict:
    """Select the media source for playback. Use only for AM, FM, USB, Bluetooth,
    or internet media, not for playback actions."""
    if source not in SOURCES:
        return err("out_of_range", f"source must be one of {sorted(SOURCES)}")
    if error := _check_preconditions(state, SOURCE_SCHEMA):
        return error
    state.set(SOURCE_PATH, source)
    return ok(state, {SOURCE_PATH: source})


def get_media_info(state: VehicleState, field: str) -> dict:
    """Read the album, artist, or track of the media currently playing.
    Use for media information, not for changing playback."""
    if field not in INFO_FIELDS:
        return err("out_of_range", f"field must be one of {sorted(INFO_FIELDS)}")
    if error := _check_preconditions(state, INFO_SCHEMA):
        return error
    key = INFO_FIELDS[field]
    return ok(state, {key: state.get(key)})
