"""agent/graph.py 테스트. 실제 LLM·MCP 없이 돈다.

모델은 정해 둔 AIMessage 를 순서대로 돌려주는 가짜이고, 도구는 tools/server.py 의 HANDLERS 를
직접 부른다. 도구 이름은 코드에 쓰지 않고 tools.json 에서 조건으로 골라 쓴다.
"""

from __future__ import annotations

import asyncio
import json
import re

import pytest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import StructuredTool
from pydantic import Field

from agent.graph import build_graph, load_tool_specs, normalize_tool_result
from agent.prompts import DOMAIN_LABELS, ERROR_MESSAGES
from sim.state import VehicleState, err
from tools.server import HANDLERS

SPECS = load_tool_specs()
POWER = "Vehicle.LowVoltageSystemState"
SPEED = "Vehicle.Speed"


def pick(predicate) -> str:
    """조건에 맞는 첫 도구 이름."""
    return next(name for name, spec in SPECS.items() if predicate(spec))


def required_rule(name: str) -> tuple[str, dict]:
    """도구의 첫 required 인자 이름과 그 스키마."""
    parameters = SPECS[name]["parameters"]
    arg = parameters["required"][0]
    return arg, parameters["properties"][arg]


def has_required(kind: str):
    def check(spec: dict) -> bool:
        required = spec["parameters"]["required"]
        return bool(required) and spec["parameters"]["properties"][required[0]].get("type") == kind

    return check


# 숫자 범위가 있는 설정 도구 (정상 실행, 인자 누락, 범위 밖)
RANGE_TOOL = pick(
    lambda s: (
        has_required("integer")(s) and s["precondition"] == ["power_on"] and "{" not in s["vss"]
    )
)
# 주행 속도 제한이 걸린 도구
SPEED_TOOL = pick(lambda s: any(p.startswith("speed_below_") for p in s["precondition"]))
SPEED_LIMIT = next(
    int(m.group(1))
    for p in SPECS[SPEED_TOOL]["precondition"]
    if (m := re.match(r"speed_below_(\d+)", p))
)
# 시동이 켜져 있어야 하는 공조 on/off 도구
POWER_TOOL = pick(
    lambda s: (
        s["domain"] == "hvac" and has_required("boolean")(s) and "power_on" in s["precondition"]
    )
)


class ScriptedChatModel(FakeMessagesListChatModel):
    """responses 를 순서대로 돌려준다. 받은 메시지는 seen 에 남긴다."""

    seen: list = Field(default_factory=list)
    bound: list = Field(default_factory=list)

    def bind_tools(self, tools, **kwargs):
        self.bound.extend(tools)
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.seen.append(list(messages))
        return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


def tool_call(name: str, args: dict, call_id: str = "call_1") -> AIMessage:
    return AIMessage("", tool_calls=[{"name": name, "args": args, "id": call_id}])


def make_tools(
    state: VehicleState, calls: list, overrides: dict | None = None
) -> list[StructuredTool]:
    """tools.json 의 도구마다 HANDLERS 를 직접 부르는 가짜 도구. 호출 기록은 calls 에."""

    def make(name: str, spec: dict) -> StructuredTool:
        def run(**kwargs):
            calls.append((name, kwargs))
            if overrides and name in overrides:
                return overrides[name]
            return HANDLERS[name](state, **kwargs)

        return StructuredTool.from_function(
            func=run,
            name=name,
            description=spec["description"],
            args_schema=spec["parameters"],
            infer_schema=False,
        )

    return [make(name, spec) for name, spec in SPECS.items()]


class Harness:
    def __init__(self, responses: list[AIMessage], tool_overrides: dict | None = None):
        self.state = VehicleState()
        self.calls: list = []
        self.model = ScriptedChatModel(responses=responses)
        self.graph = build_graph(self.model, make_tools(self.state, self.calls, tool_overrides))

    def say(self, utterance: str, thread: str = "t1") -> dict:
        return asyncio.run(
            self.graph.ainvoke(
                {"messages": [HumanMessage(utterance)], "vehicle_state": self.state.snapshot()},
                {"configurable": {"thread_id": thread}},
            )
        )


def test_executes_valid_call_and_changes_state():
    arg, rule = required_rule(RANGE_TOOL)
    harness = Harness([tool_call(RANGE_TOOL, {arg: rule["maximum"]})])
    path = SPECS[RANGE_TOOL]["vss"]

    result = harness.say("끝까지 올려")

    assert result["trace"] == {
        "selected_tool": RANGE_TOOL,
        "executed_tool": RANGE_TOOL,
        "outcome": "executed",
        "code": None,
    }
    assert result["tool_result"]["state_after"] == {path: rule["maximum"]}
    assert harness.state.get(path) == rule["maximum"]
    assert result["final_answer"].startswith(DOMAIN_LABELS[SPECS[RANGE_TOOL]["domain"]])
    assert str(rule["maximum"]) in result["final_answer"]
    assert harness.calls == [(RANGE_TOOL, {arg: rule["maximum"]})]


def test_missing_required_argument_asks_with_ask_prompt():
    arg, _ = required_rule(RANGE_TOOL)
    harness = Harness([tool_call(RANGE_TOOL, {})])

    result = harness.say("그거 좀 바꿔줘")

    assert result["ask"] == SPECS[RANGE_TOOL]["ask_prompt"][arg]
    assert result["final_answer"] == result["ask"]
    assert result["trace"]["outcome"] == "asked"
    assert result["trace"]["code"] == "missing_arg"
    assert result["trace"]["executed_tool"] is None
    assert harness.calls == []


def test_out_of_range_value_is_refused():
    arg, rule = required_rule(RANGE_TOOL)
    harness = Harness([tool_call(RANGE_TOOL, {arg: rule["maximum"] + 1})])

    result = harness.say("엄청 크게")

    assert result["tool_result"]["code"] == "out_of_range"
    assert result["trace"]["outcome"] == "refused"
    assert result["final_answer"] == ERROR_MESSAGES["out_of_range"]
    assert harness.calls == []


def test_speed_limited_tool_is_refused_while_driving():
    arg, rule = required_rule(SPEED_TOOL)
    harness = Harness([tool_call(SPEED_TOOL, {arg: rule["maximum"]})])
    harness.state.set(SPEED, SPEED_LIMIT + 20)

    result = harness.say("창문 열어")

    assert result["trace"] == {
        "selected_tool": SPEED_TOOL,
        "executed_tool": None,
        "outcome": "refused",
        "code": "unsafe_while_driving",
    }
    assert result["final_answer"] == ERROR_MESSAGES["unsafe_while_driving"]
    assert harness.calls == []


def test_power_off_is_refused_with_engine_off():
    arg, _ = required_rule(POWER_TOOL)
    harness = Harness([tool_call(POWER_TOOL, {arg: True})])
    harness.state.set(POWER, "OFF")

    result = harness.say("에어컨 켜")

    assert result["tool_result"]["code"] == "engine_off"
    assert result["trace"]["outcome"] == "refused"
    assert result["trace"]["executed_tool"] is None
    assert harness.calls == []


def test_no_tool_call_answers_without_tools():
    harness = Harness([AIMessage("오늘 날씨 좋네요.")])

    result = harness.say("오늘 날씨 좋다")

    assert result["tool_call"] is None
    assert result["trace"] == {
        "selected_tool": None,
        "executed_tool": None,
        "outcome": "no_tool",
        "code": None,
    }
    assert result["final_answer"] == "오늘 날씨 좋네요."
    assert harness.calls == []


def test_question_without_tool_call_counts_as_asked():
    harness = Harness([AIMessage("창문을 열까요, 닫을까요?")])

    result = harness.say("창문")

    assert result["tool_call"] is None
    assert result["ask"] == "창문을 열까요, 닫을까요?"
    assert result["final_answer"] == result["ask"]
    assert result["trace"] == {
        "selected_tool": None,
        "executed_tool": None,
        "outcome": "asked",
        "code": None,
    }


def test_model_may_pass_null_for_required_arguments():
    harness = Harness([AIMessage("네.")])
    shown = {schema["function"]["name"]: schema["function"] for schema in harness.model.bound}

    assert set(shown) == set(SPECS)
    for name, function in shown.items():
        assert function["description"] == SPECS[name]["description"]
        for required in SPECS[name]["parameters"]["required"]:
            prop = function["parameters"]["properties"][required]
            assert "null" in prop["type"]
            assert "enum" not in prop or None in prop["enum"]
            assert prop["description"].startswith("Required")
            # 검증 기준인 tools.json 은 null 을 허용하지 않는 그대로다
            assert SPECS[name]["parameters"]["properties"][required]["type"] != prop["type"]


def test_null_for_required_argument_asks():
    arg, _ = required_rule(RANGE_TOOL)
    harness = Harness([tool_call(RANGE_TOOL, {arg: None})])

    result = harness.say("그거 좀 바꿔줘")

    assert result["ask"] == SPECS[RANGE_TOOL]["ask_prompt"][arg]
    assert result["trace"]["outcome"] == "asked"
    assert harness.calls == []


@pytest.mark.parametrize("reply", ["어디로 안내할까요?", "목적지를 말씀해 주세요. (예: 집, 회사)"])
def test_text_that_asks_the_user_counts_as_asked(reply: str):
    harness = Harness([AIMessage(reply)])

    assert harness.say("길 안내")["trace"]["outcome"] == "asked"


def test_answer_after_ask_runs_the_same_tool_in_same_thread():
    arg, rule = required_rule(RANGE_TOOL)
    harness = Harness(
        [
            tool_call(RANGE_TOOL, {}, "call_1"),
            tool_call(RANGE_TOOL, {arg: rule["minimum"]}, "call_2"),
        ]
    )

    first = harness.say("그거 좀 바꿔줘")
    second = harness.say("제일 작게")

    assert first["trace"]["outcome"] == "asked"
    assert second["trace"]["outcome"] == "executed"
    assert second["trace"]["executed_tool"] == RANGE_TOOL
    assert second["ask"] is None
    assert harness.state.get(SPECS[RANGE_TOOL]["vss"]) == rule["minimum"]
    # 두 번째 호출에서 모델은 첫 턴의 도구 호출과 되묻는 문장을 본다
    history = harness.model.seen[1]
    assert [m.content for m in history if isinstance(m, HumanMessage)] == [
        "그거 좀 바꿔줘",
        "제일 작게",
    ]
    assert any(isinstance(m, AIMessage) and m.content == first["ask"] for m in history)
    assert any(isinstance(m, ToolMessage) for m in history)
    assert len(second["messages"]) == 8  # 턴마다 발화, 도구 호출, 도구 결과, 최종 답


def test_other_thread_does_not_share_history():
    arg, rule = required_rule(RANGE_TOOL)
    harness = Harness([tool_call(RANGE_TOOL, {}), tool_call(RANGE_TOOL, {arg: rule["minimum"]})])

    harness.say("그거 좀 바꿔줘", thread="a")
    harness.say("제일 작게", thread="b")

    assert [m.content for m in harness.model.seen[1] if isinstance(m, HumanMessage)] == [
        "제일 작게"
    ]


def test_error_from_inside_tool_is_refused():
    """검증은 통과했지만 도구 함수가 막은 경우 (주행 중 잠금 해제 같은 것)."""
    arg, rule = required_rule(RANGE_TOOL)
    blocked = json.dumps(err("unsafe_while_driving", "blocked inside tool"))
    harness = Harness(
        [tool_call(RANGE_TOOL, {arg: rule["maximum"]})], tool_overrides={RANGE_TOOL: blocked}
    )

    result = harness.say("끝까지 올려")

    assert harness.calls == [(RANGE_TOOL, {arg: rule["maximum"]})]
    assert result["trace"] == {
        "selected_tool": RANGE_TOOL,
        "executed_tool": None,
        "outcome": "refused",
        "code": "unsafe_while_driving",
    }
    assert result["final_answer"] == ERROR_MESSAGES["unsafe_while_driving"]


def test_unknown_tool_name_is_refused():
    harness = Harness([tool_call("no_such_tool_in_tools_json", {})])

    result = harness.say("자동 주차해줘")

    assert result["tool_result"]["code"] == "unknown_tool"
    assert result["trace"]["outcome"] == "refused"
    assert harness.calls == []


def test_only_first_tool_call_is_used():
    arg, rule = required_rule(RANGE_TOOL)
    power_arg, _ = required_rule(POWER_TOOL)
    both = AIMessage(
        "",
        tool_calls=[
            {"name": RANGE_TOOL, "args": {arg: rule["maximum"]}, "id": "call_1"},
            {"name": POWER_TOOL, "args": {power_arg: True}, "id": "call_2"},
        ],
    )
    harness = Harness([both])

    result = harness.say("둘 다 해줘")

    assert result["trace"]["executed_tool"] == RANGE_TOOL
    assert [name for name, _ in harness.calls] == [RANGE_TOOL]


@pytest.mark.parametrize("wrap", ["dict", "json", "tool_message", "blocks"])
def test_normalize_tool_result_accepts_every_shape(wrap: str):
    payload = {"status": "ok", "code": None, "state_after": {SPEED: 0}}
    text = json.dumps(payload)
    raw = {
        "dict": payload,
        "json": text,
        "tool_message": ToolMessage(text, tool_call_id="call_1"),
        "blocks": [{"type": "text", "text": text}],
    }[wrap]

    result = normalize_tool_result(raw)

    assert (result["status"], result["code"], result["state_after"]) == ("ok", None, {SPEED: 0})


def test_normalize_tool_result_rejects_garbage():
    assert normalize_tool_result("not json")["status"] == "error"
    assert normalize_tool_result({"unexpected": 1})["status"] == "error"
