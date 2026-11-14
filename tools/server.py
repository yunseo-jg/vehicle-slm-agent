"""MCP 도구 서버. stdio 로 실행.

    python tools/server.py

ontology/generated/tools.json 의 도구를 전부 자동 등록한다.
이름·설명·파라미터 스키마는 생성물에서 오고, 실행은 도메인 모듈(tools/<domain>.py)의
HANDLERS[이름](state, **kwargs) 가 맡는다. 구현이 아직 없는 도구는 건너뛰고 stderr 에 남긴다.
반환 형식은 sim.state.ok / err 만 쓴다.

MCP Python SDK 2.x 기준 (FastMCP 가 MCPServer 로 이름이 바뀜). 1.x 예제를 따라 하지 않는다.
"""

from __future__ import annotations

import inspect
import json
import logging
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any, Literal

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mcp.server.mcpserver import MCPServer  # noqa: E402
from mcp_types import ToolAnnotations  # noqa: E402
from pydantic import Field  # noqa: E402

from sim.state import VehicleState  # noqa: E402
from tools import hvac as hvac_tools  # noqa: E402
from tools import media as media_tools  # noqa: E402
from tools import nav as nav_tools  # noqa: E402
from tools import settings as settings_tools  # noqa: E402
from tools import status as status_tools  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
TOOLS_SCHEMA = ROOT / "ontology" / "generated" / "tools.json"

log = logging.getLogger(__name__)

mcp = MCPServer("vehicle")
state = VehicleState()

# 도구 이름 → 구현. 도메인 모듈을 추가하면 여기에 HANDLERS 를 합친다
HANDLERS: dict[str, Callable[..., dict]] = {
    **hvac_tools.HANDLERS,
    **media_tools.HANDLERS,
    **nav_tools.HANDLERS,
    **status_tools.HANDLERS,
    **settings_tools.HANDLERS,
}

JSON_TYPES = {"integer": int, "number": float, "string": str, "boolean": bool}


def _load_tools() -> list[dict]:
    with TOOLS_SCHEMA.open(encoding="utf-8") as file:
        return json.load(file)


def _annotation(prop: dict) -> Any:
    """JSON Schema 속성 하나 → 파이썬 타입 힌트. enum 은 Literal, min/max 는 Field 제약."""
    if "enum" in prop:
        return Literal[tuple(prop["enum"])]
    py_type = JSON_TYPES[prop["type"]]
    bounds = {k: prop[j] for k, j in (("ge", "minimum"), ("le", "maximum")) if j in prop}
    if bounds:
        return Annotated[py_type, Field(**bounds)]
    return py_type


def _signature(schema: dict) -> inspect.Signature:
    """tools.json 의 parameters 를 inspect.Signature 로. SDK 가 이걸 읽어 입력 스키마를 만든다."""
    required = set(schema["parameters"]["required"])
    params = []
    for name, prop in schema["parameters"]["properties"].items():
        annotation = _annotation(prop)
        default = inspect.Parameter.empty
        if name not in required:
            default = prop.get("default")
            if default is None:
                annotation = annotation | None
        params.append(
            inspect.Parameter(
                name, inspect.Parameter.KEYWORD_ONLY, default=default, annotation=annotation
            )
        )
    return inspect.Signature(params, return_annotation=dict)


def _make_tool(name: str, handler: Callable[..., dict], signature: inspect.Signature) -> Callable:
    def tool(**kwargs) -> dict:
        return handler(state, **kwargs)

    tool.__name__ = name
    tool.__signature__ = signature  # type: ignore[attr-defined]
    return tool


def _register_all() -> list[str]:
    registered = []
    for schema in _load_tools():
        name = schema["name"]
        handler = HANDLERS.get(name)
        if handler is None:
            log.warning("tools.json 의 %s 에 구현(HANDLERS)이 없어 등록하지 않음", name)
            continue
        mcp.add_tool(
            _make_tool(name, handler, _signature(schema)),
            name=name,
            description=schema["description"],
            annotations=ToolAnnotations(read_only_hint=name.startswith("get_")),
        )
        registered.append(name)
    return registered


REGISTERED = _register_all()


if __name__ == "__main__":
    mcp.run()
