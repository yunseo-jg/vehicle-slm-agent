"""차량 도구를 한 번만 호출하는 최소 LangGraph 에이전트."""

from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from typing import Annotated, Any, Literal

from langchain_core.messages import AIMessage, AnyMessage, SystemMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict

from agent.prompts import SYSTEM

ROOT = Path(__file__).resolve().parent.parent
TOOLS_SCHEMA = ROOT / "ontology" / "generated" / "tools.json"


class AgentState(TypedDict, total=False):
    """그래프의 노드가 공유하는 상태."""

    messages: Annotated[list[AnyMessage], add_messages]
    vehicle_state: dict[str, Any]
    needs_tool: bool
    tool_call: dict[str, Any] | None
    tool_result: dict[str, Any] | None
    ask: str | None
    final_answer: str | None


TOOL_KEYWORDS = (
    "에어컨",
    "온도",
    "차량",
    "배터리",
    "주행 거리",
    "남았",
    "속도",
    "몇 킬로",
)

ERROR_MESSAGES = {
    "engine_off": "차량 전원이 꺼져 있어 실행할 수 없습니다.",
    "out_of_range": "설정 가능한 범위를 벗어났습니다.",
    "missing_arg": "필요한 값을 확인해 주세요.",
    "unsafe_while_driving": "주행 중에는 안전을 위해 실행할 수 없습니다.",
    "not_found": "요청한 항목을 찾지 못했습니다.",
    "unknown_tool": "지원하지 않는 기능입니다.",
}

ASK_PROMPTS = {
    "value": "몇 도로 맞춰드릴까요?",
    "field": "배터리, 주행 가능 거리, 속도 중 무엇을 확인할까요?",
}


def _error(code: str, message: str = "") -> dict[str, Any]:
    return {"status": "error", "code": code, "message": message, "state_after": {}}


def _load_schemas() -> dict[str, dict[str, Any]]:
    with TOOLS_SCHEMA.open(encoding="utf-8") as file:
        return {item["name"]: item for item in json.load(file)}


def intent_node(state: AgentState) -> dict[str, bool]:
    """간단한 키워드 규칙으로 도구 필요 여부를 판별한다."""

    text = str(state["messages"][-1].content)
    return {"needs_tool": any(keyword in text for keyword in TOOL_KEYWORDS)}


def make_tool_select_node(llm: Any, tools: list[Any]):
    """MCP 도구 스키마를 모델에 전달하고 한 개의 도구 호출을 고른다."""

    llm_with_tools = llm.bind_tools(tools)

    async def tool_select(state: AgentState) -> dict[str, Any]:
        system = SystemMessage(
            content=SYSTEM.format(
                vehicle_state=json.dumps(state.get("vehicle_state", {}), ensure_ascii=False)
            )
        )
        response = await llm_with_tools.ainvoke([system, *state["messages"][-10:]])

        if not response.tool_calls:
            return {
                "messages": [response],
                "tool_call": None,
                "tool_result": _error("unknown_tool"),
            }

        call = response.tool_calls[0]
        return {
            "messages": [response],
            "tool_call": {
                "name": call["name"],
                "args": dict(call["args"]),
                "id": call.get("id") or f"call_{uuid.uuid4().hex}",
            },
            "tool_result": None,
            "ask": None,
        }

    return tool_select


def _check_preconditions(preconditions: list[str], vehicle_state: dict[str, Any]) -> str | None:
    power = vehicle_state.get("Vehicle.LowVoltageSystemState")
    speed = float(vehicle_state.get("Vehicle.Speed", 0))

    for precondition in preconditions:
        if precondition == "power_on" and power not in {"ON", "START"}:
            return "engine_off"
        if precondition == "parked" and speed > 0:
            return "unsafe_while_driving"
        if match := re.fullmatch(r"speed_below_(\d+)", precondition):
            if speed >= int(match.group(1)):
                return "unsafe_while_driving"
    return None


def make_validate_node(available_tool_names: set[str]):
    """온톨로지의 required, enum, 범위, precondition을 코드로 검사한다."""

    schemas = _load_schemas()

    def validate(state: AgentState) -> dict[str, Any]:
        call = state.get("tool_call")
        if call is None or call["name"] not in available_tool_names:
            return {"tool_result": _error("unknown_tool")}

        schema = schemas.get(call["name"])
        if schema is None:
            return {"tool_result": _error("unknown_tool")}

        args = call["args"]
        parameters = schema["parameters"]
        properties = parameters.get("properties", {})

        for name, definition in properties.items():
            if name not in args and "default" in definition:
                args[name] = definition["default"]

        missing = [name for name in parameters.get("required", []) if name not in args]
        if missing:
            missing_name = missing[0]
            return {
                "ask": ASK_PROMPTS.get(missing_name, f"{missing_name} 값을 알려주세요."),
                "tool_result": _error("missing_arg"),
            }

        if parameters.get("additionalProperties") is False and set(args) - set(properties):
            return {"tool_result": _error("out_of_range")}

        for name, value in args.items():
            definition = properties.get(name, {})
            expected_type = definition.get("type")
            if expected_type == "integer" and (
                not isinstance(value, int) or isinstance(value, bool)
            ):
                return {"tool_result": _error("out_of_range")}
            if expected_type == "string" and not isinstance(value, str):
                return {"tool_result": _error("out_of_range")}
            if "enum" in definition and value not in definition["enum"]:
                return {"tool_result": _error("out_of_range")}
            if "minimum" in definition and value < definition["minimum"]:
                return {"tool_result": _error("out_of_range")}
            if "maximum" in definition and value > definition["maximum"]:
                return {"tool_result": _error("out_of_range")}

        code = _check_preconditions(schema.get("precondition", []), state["vehicle_state"])
        if code:
            return {"tool_result": _error(code)}

        return {"ask": None, "tool_call": call, "tool_result": None}

    return validate


def _normalize_result(result: Any) -> dict[str, Any]:
    if isinstance(result, dict):
        return result
    if isinstance(result, ToolMessage):
        artifact = result.artifact or {}
        structured = artifact.get("structured_content")
        if isinstance(structured, dict):
            return structured
        result = result.content
    if isinstance(result, list):
        texts = [
            block.get("text", "")
            for block in result
            if isinstance(block, dict) and block.get("type") == "text"
        ]
        result = "".join(texts)
    if isinstance(result, str):
        try:
            parsed = json.loads(result)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
    return _error("unknown_tool", f"unexpected tool result: {result!r}")


def make_execute_node(tools: list[Any]):
    """검증을 통과한 호출만 MCP 도구로 전달한다."""

    tools_by_name = {tool.name: tool for tool in tools}

    async def execute(state: AgentState) -> dict[str, Any]:
        call = state.get("tool_call")
        if call is None or call["name"] not in tools_by_name:
            return {"tool_result": _error("unknown_tool")}

        result = _normalize_result(await tools_by_name[call["name"]].ainvoke(call["args"]))
        tool_message = ToolMessage(
            content=json.dumps(result, ensure_ascii=False),
            tool_call_id=call["id"],
            name=call["name"],
        )
        return {"messages": [tool_message], "tool_result": result}

    return execute


def _success_message(state: AgentState) -> str:
    call = state.get("tool_call") or {}
    args = call.get("args", {})
    result = state.get("tool_result") or {}

    if call.get("name") == "set_hvac_temperature":
        zones = {"driver": "운전석", "passenger": "동승석", "rear": "뒷좌석"}
        zone = zones.get(args.get("zone", "driver"), "선택한 좌석")
        return f"{zone} 온도를 {args.get('value')}도로 설정했습니다."
    if call.get("name") == "get_vehicle_state":
        labels = {"battery": "배터리", "range": "주행 가능 거리", "speed": "현재 속도"}
        state_after = result.get("state_after", {})
        value = next(iter(state_after.values()), "알 수 없음")
        return f"{labels.get(args.get('field'), '차량 상태')}는 {value}입니다."
    return "요청한 차량 기능을 실행했습니다."


def respond_node(state: AgentState) -> dict[str, Any]:
    """실행 결과 또는 에러 코드를 한국어 한 문장으로 변환한다."""

    if state.get("ask"):
        answer = state["ask"]
    elif not state.get("needs_tool"):
        answer = "차량 기능과 관련해 무엇을 도와드릴까요?"
    else:
        result = state.get("tool_result") or {}
        if result.get("status") == "ok":
            answer = _success_message(state)
        else:
            answer = ERROR_MESSAGES.get(result.get("code"), "요청을 실행하지 못했습니다.")

    messages: list[AnyMessage] = []
    call = state.get("tool_call")
    if call and not isinstance(state["messages"][-1], ToolMessage):
        messages.append(
            ToolMessage(
                content=json.dumps(state.get("tool_result") or {}, ensure_ascii=False),
                tool_call_id=call["id"],
                name=call["name"],
            )
        )
    messages.append(AIMessage(content=answer))
    return {"messages": messages, "final_answer": answer}


def route_after_intent(state: AgentState) -> Literal["tool_select", "respond"]:
    return "tool_select" if state["needs_tool"] else "respond"


def route_after_validate(state: AgentState) -> Literal["execute", "respond"]:
    result = state.get("tool_result")
    if state.get("ask") or (result and result.get("status") == "error"):
        return "respond"
    return "execute"


def build_graph(llm: Any, tools: list[Any], checkpointer: Any | None = None):
    """모델과 MCP 도구를 주입받아 컴파일된 5노드 그래프를 반환한다."""

    if llm is None:
        raise ValueError("llm is required")
    if not tools:
        raise ValueError("at least one tool is required")

    builder = StateGraph(AgentState)
    builder.add_node("intent", intent_node)
    builder.add_node("tool_select", make_tool_select_node(llm, tools))
    builder.add_node("validate", make_validate_node({tool.name for tool in tools}))
    builder.add_node("execute", make_execute_node(tools))
    builder.add_node("respond", respond_node)

    builder.add_edge(START, "intent")
    builder.add_conditional_edges("intent", route_after_intent)
    builder.add_edge("tool_select", "validate")
    builder.add_conditional_edges("validate", route_after_validate)
    builder.add_edge("execute", "respond")
    builder.add_edge("respond", END)

    return builder.compile(checkpointer=checkpointer or InMemorySaver())
