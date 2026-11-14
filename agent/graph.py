"""LangGraph 에이전트.

원칙: 모델은 도구와 인자를 고르기만 한다. 검증·실행·응답 문장은 코드가 담당한다.
도구 정보(이름, 파라미터, precondition, ask_prompt, domain)는 전부
ontology/generated/tools.json 에서 읽고, 도구 이름을 코드에 쓰지 않는다.

노드
  tool_select  llm.bind_tools(...) 로 모델을 1회 호출. 최근 메시지 10개와
               현재 차량 상태가 들어간 시스템 프롬프트를 넘긴다. 첫 번째 tool_call 만 쓴다.
               모델에게 보여주는 도구 정의는 tools.json 에서 만들되 필수 인자에 null 을 허용한다
               (모델은 모르는 값을 null 로 넘기고, validate 가 누락으로 잡아 되묻는다).
               도구 없이 질문으로 답하면 모델이 직접 되물은 것으로 보고 outcome=asked
  validate     모델 없이 tools.json 만으로 검사. 순서대로
               (a) 모르는 도구 → unknown_tool
               (b) required 인자 누락 → 그 인자의 ask_prompt 로 되묻기 (missing_arg)
               (c) enum 밖, min/max 밖, 타입 불일치, 스키마에 없는 인자 → out_of_range
               (d) precondition 위반 → sim.state 가 주는 코드 (engine_off, unsafe_while_driving)
  execute      tools_by_name[name].ainvoke(args). 결과를 {status, code, state_after} 로 정규화.
               도구 함수 안에서 막힌 경우(주행 중 잠금 해제 등)도 거절로 처리
  respond      되묻기 문장 / 에러 코드별 고정 문장 / 완료 템플릿 / 도구 없음 응답 중 하나.
               모델을 다시 부르지 않는다

분기
  tool_select ─(tool_call 없음)──────────────▶ respond
              └(있음)▶ validate ─(ask 또는 error)▶ respond
                                └(통과)▶ execute ─▶ respond ─▶ END

상태(AgentState)
  messages       대화 히스토리. 같은 thread_id 면 checkpointer 가 이어 준다.
                 한 턴이 끝날 때 respond 가 (도구 호출 AIMessage, ToolMessage, 최종 답) 을
                 한 번에 쌓는다
  vehicle_state  현재 차량 상태 스냅샷. 매 턴 호출부가 새로 넣는다. 과거 값을 재사용하지 않는다
  tool_call      모델이 고른 도구 {name, args, id}. 없으면 None
  tool_result    검증 실패 또는 실행 결과 {status, code, state_after}
  ask            되묻는 문장. 없으면 None
  final_answer   사용자에게 보여줄 한 문장
  trace          평가 기록용 {selected_tool, executed_tool, outcome, code}
                 outcome 은 executed | asked | refused | no_tool.
                 asked 인데 selected_tool 이 None 이면 모델이 직접 되물은 것 (code 도 None)

모델 교체(클라우드 ↔ Ollama)는 build_graph(llm=...) 인자만 바꾸면 된다.
"""

from __future__ import annotations

import copy
import json
import uuid
from collections.abc import Sequence
from pathlib import Path
from typing import Annotated, Any, TypedDict

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import BaseTool
from langchain_core.utils.function_calling import convert_to_openai_tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from agent.prompts import DOMAIN_LABELS, ERROR_FALLBACK, ERROR_MESSAGES, NO_TOOL_MESSAGE, SYSTEM
from sim.state import PreconditionError, VehicleState

ROOT = Path(__file__).resolve().parent.parent
TOOLS_SCHEMA = ROOT / "ontology" / "generated" / "tools.json"

HISTORY_LIMIT = 10
REQUIRED_HINT = "Required. Pass null if the user did not state it; never guess"
JSON_TYPES: dict[str, tuple[type, ...]] = {
    "integer": (int,),
    "number": (int, float),
    "string": (str,),
    "boolean": (bool,),
}


class AgentState(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    vehicle_state: dict[str, Any]
    tool_call: dict[str, Any] | None
    tool_result: dict[str, Any] | None
    ask: str | None
    final_answer: str
    trace: dict[str, Any]


def load_tool_specs(path: Path = TOOLS_SCHEMA) -> dict[str, dict]:
    with path.open(encoding="utf-8") as file:
        return {tool["name"]: tool for tool in json.load(file)}


def _error(code: str | None, message: str = "") -> dict:
    return {"status": "error", "code": code, "message": message, "state_after": {}}


def _recent(messages: Sequence[AnyMessage]) -> list[AnyMessage]:
    """최근 HISTORY_LIMIT 개. 잘린 자리가 도구 호출 중간이면 다음 사용자 발화부터 시작한다."""
    recent = list(messages[-HISTORY_LIMIT:])
    while recent and not isinstance(recent[0], HumanMessage):
        recent.pop(0)
    return recent


def _check_value(name: str, value: Any, rule: dict) -> tuple[Any, str | None]:
    """값 하나를 스키마 속성과 대조. (정리된 값, 에러 메시지 또는 None)"""
    if "enum" in rule:
        if value not in rule["enum"]:
            return value, f"{name} must be one of {rule['enum']}"
        return value, None
    kind = rule["type"]
    if kind == "integer" and isinstance(value, float) and value.is_integer():
        value = int(value)  # 22.0 처럼 정수인 실수는 받아 준다
    if isinstance(value, bool) != (kind == "boolean") or not isinstance(value, JSON_TYPES[kind]):
        return value, f"{name} must be {kind}"
    if (
        "minimum" in rule
        and value < rule["minimum"]
        or "maximum" in rule
        and value > rule["maximum"]
    ):
        return value, f"{name} must be from {rule.get('minimum')} to {rule.get('maximum')}"
    return value, None


def normalize_tool_result(raw: Any) -> dict:
    """도구 결과를 {status, code, state_after} dict 로.

    ToolMessage, 문자열, 내용 블록 목록, dict 를 받는다.
    """
    if isinstance(raw, tuple):  # (content, artifact)
        raw = raw[0]
    if isinstance(raw, ToolMessage):
        raw = raw.content
    if isinstance(raw, list):  # MCP 내용 블록 목록
        raw = "".join(
            block.get("text", "") if isinstance(block, dict) else getattr(block, "text", str(block))
            for block in raw
        )
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return _error(None, f"unreadable tool result: {raw[:200]}")
    if not isinstance(raw, dict) or raw.get("status") not in {"ok", "error"}:
        return _error(None, f"unexpected tool result: {str(raw)[:200]}")
    return {
        "status": raw["status"],
        "code": raw.get("code"),
        "message": raw.get("message", ""),
        "state_after": raw.get("state_after") or {},
    }


def model_tool_schemas(tools: Sequence[BaseTool], specs: dict[str, dict]) -> list[dict]:
    """모델에게 보여줄 도구 정의. tools.json 의 설명·파라미터를 쓰되 필수 인자에 null 을 허용한다.

    필수 인자에 값만 허용하면 모델이 값을 지어내거나 도구를 안 부르고 글로 되묻는다.
    그래서 "사용자가 말하지 않았으면 null" 이라는 선택지를 스키마에 넣어 주고,
    null 로 온 필수 인자는 validate 가 누락으로 잡아 되묻는다. 검증 기준(tools.json)은 그대로다.
    """
    schemas = []
    for tool in tools:
        spec = specs.get(tool.name)
        if spec is None:  # tools.json 에 없는 도구는 받은 그대로
            schemas.append(convert_to_openai_tool(tool))
            continue
        parameters = copy.deepcopy(spec["parameters"])
        for name in parameters["required"]:
            prop = parameters["properties"][name]
            prop["type"] = [prop["type"], "null"]
            if "enum" in prop:
                prop["enum"] = [*prop["enum"], None]
            prop["description"] = ". ".join(filter(None, [REQUIRED_HINT, prop.get("description")]))
        function = {"name": spec["name"], "description": spec["description"]}
        schemas.append({"type": "function", "function": function | {"parameters": parameters}})
    return schemas


def _is_question(text: str) -> bool:
    """도구 없이 온 답이 사용자에게 되묻는 문장인지. 물음표나 "주세요" 가 있으면 그렇게 본다."""
    return any(mark in text for mark in ("?", "？", "주세요"))


def _format_value(value: Any) -> str:
    if isinstance(value, bool):
        return "켜짐" if value else "꺼짐"
    return str(value)


def _success_sentence(spec: dict, state_after: dict) -> str:
    """완료 문장. 도메인 이름과 바뀐(또는 읽은) 값만으로 만든다."""
    domain = DOMAIN_LABELS.get(spec["domain"], spec["domain"])
    counts: dict[str, int] = {}
    for key, value in state_after.items():
        item = f"{key.rsplit('.', 1)[-1]} {_format_value(value)}"
        counts[item] = counts.get(item, 0) + 1
    items = ", ".join(f"{item} ({n}곳)" if n > 1 else item for item, n in counts.items())
    if spec["name"].startswith("get_"):  # 읽기 도구. tools/server.py 의 read_only_hint 와 같은 기준
        return f"{domain} 정보예요: {items}." if items else f"{domain} 정보를 확인했어요."
    return f"{domain} 설정을 바꿨어요: {items}." if items else f"{domain} 설정을 바꿨어요."


def build_graph(
    llm: BaseChatModel,
    tools: Sequence[BaseTool],
    checkpointer: Any = None,
    specs: dict[str, dict] | None = None,
):
    """에이전트 그래프를 만든다. `await graph.ainvoke({...}, config)` 로 한 턴을 돌린다.

    입력은 {"messages": [HumanMessage(발화)], "vehicle_state": 현재 상태 dict},
    config 는 {"configurable": {"thread_id": ...}}. 같은 thread_id 면 대화가 이어진다.
    """
    specs = specs if specs is not None else load_tool_specs()
    tools_by_name = {tool.name: tool for tool in tools}
    model = llm.bind_tools(model_tool_schemas(tools, specs))

    async def tool_select(state: AgentState) -> dict:
        vehicle_state = json.dumps(state.get("vehicle_state", {}), ensure_ascii=False, indent=1)
        system = SystemMessage(SYSTEM.format(vehicle_state=vehicle_state))
        reply = await model.ainvoke([system, *_recent(state["messages"])])
        update: dict = {"tool_result": None, "ask": None, "final_answer": ""}
        calls = getattr(reply, "tool_calls", None) or []
        if not calls:
            text = (reply.content if isinstance(reply.content, str) else "").strip()
            asked = _is_question(text)  # 도구 없이 질문으로 답했으면 모델이 직접 되물은 것
            return update | {
                "tool_call": None,
                "ask": text if asked else None,
                "final_answer": text,
                "trace": _trace(None, None, "asked" if asked else "no_tool", None),
            }
        call = calls[0]
        tool_call = {
            "name": call["name"],
            "args": dict(call.get("args") or {}),
            "id": call.get("id") or f"call_{uuid.uuid4().hex}",
        }
        return update | {
            "tool_call": tool_call,
            "trace": _trace(tool_call["name"], None, None, None),
        }

    def validate(state: AgentState) -> dict:
        call = state["tool_call"]
        name, args = call["name"], call["args"]
        spec = specs.get(name)
        if spec is None:
            return _refuse(name, _error("unknown_tool", f"unknown tool: {name}"))
        properties = spec["parameters"]["properties"]
        for required in spec["parameters"]["required"]:
            if args.get(required) in (None, ""):
                ask = spec.get("ask_prompt", {}).get(required) or ERROR_MESSAGES["missing_arg"]
                return {
                    "ask": ask,
                    "tool_result": _error("missing_arg", f"{required} is required"),
                    "trace": _trace(name, None, "asked", "missing_arg"),
                }
        cleaned = {}
        for arg, value in args.items():
            if value is None and arg not in spec["parameters"]["required"]:
                continue  # 선택 인자를 null 로 준 것은 생략으로 본다
            if arg not in properties:
                return _refuse(name, _error("out_of_range", f"unknown argument: {arg}"))
            cleaned[arg], problem = _check_value(arg, value, properties[arg])
            if problem:
                return _refuse(name, _error("out_of_range", problem))
        try:
            VehicleState(dict(state.get("vehicle_state") or {})).check(spec["precondition"])
        except PreconditionError as error:
            return _refuse(name, _error(error.code, str(error)))
        return {"tool_call": call | {"args": cleaned}, "tool_result": None}

    async def execute(state: AgentState) -> dict:
        call = state["tool_call"]
        name = call["name"]
        tool = tools_by_name.get(name)
        if tool is None:
            return _refuse(name, _error("unknown_tool", f"tool not available: {name}"))
        try:
            result = normalize_tool_result(await tool.ainvoke(call["args"]))
        except Exception as error:  # noqa: BLE001  도구 호출 실패도 거절 응답으로 끝낸다
            result = _error(None, f"tool call failed: {error}")
        if result["status"] != "ok":
            return _refuse(name, result)
        return {"tool_result": result, "trace": _trace(name, name, "executed", None)}

    def respond(state: AgentState) -> dict:
        call = state.get("tool_call")
        result = state.get("tool_result")
        if call is None:
            answer = state.get("final_answer") or NO_TOOL_MESSAGE
            return {"final_answer": answer, "messages": [AIMessage(answer)]}
        if state.get("ask"):
            answer = state["ask"]
        elif result["status"] == "error":
            answer = ERROR_MESSAGES.get(result["code"], ERROR_FALLBACK)
        else:
            answer = _success_sentence(specs[call["name"]], result["state_after"])
        tool_call = {"name": call["name"], "args": call["args"], "id": call["id"]}
        history = [
            AIMessage("", tool_calls=[tool_call]),
            ToolMessage(json.dumps(result, ensure_ascii=False), tool_call_id=call["id"]),
            AIMessage(answer),
        ]
        return {"final_answer": answer, "messages": history}

    def after_select(state: AgentState) -> str:
        return "validate" if state.get("tool_call") else "respond"

    def after_validate(state: AgentState) -> str:
        return "respond" if state.get("ask") or state.get("tool_result") else "execute"

    builder = StateGraph(AgentState)
    builder.add_node("tool_select", tool_select)
    builder.add_node("validate", validate)
    builder.add_node("execute", execute)
    builder.add_node("respond", respond)
    builder.add_edge(START, "tool_select")
    builder.add_conditional_edges("tool_select", after_select, ["validate", "respond"])
    builder.add_conditional_edges("validate", after_validate, ["execute", "respond"])
    builder.add_edge("execute", "respond")
    builder.add_edge("respond", END)
    return builder.compile(
        checkpointer=checkpointer if checkpointer is not None else InMemorySaver()
    )


def _trace(
    selected: str | None, executed: str | None, outcome: str | None, code: str | None
) -> dict:
    return {
        "selected_tool": selected,
        "executed_tool": executed,
        "outcome": outcome,
        "code": code,
    }


def _refuse(name: str, result: dict) -> dict:
    return {"tool_result": result, "trace": _trace(name, None, "refused", result["code"])}
