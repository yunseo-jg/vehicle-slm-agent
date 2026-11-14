"""eval/run_eval.py, eval/score.py 테스트. 실제 LLM 없이 가짜 모델과 in-process MCP 서버로 돈다."""

from __future__ import annotations

import asyncio

import pytest
from langchain_core.messages import AIMessage

from agent.graph import load_tool_specs
from eval.run_eval import agent_graph, run_case, run_cases
from eval.score import (
    arg_acc,
    percentile,
    score_record,
    summarize,
    task_success,
    to_markdown,
    tool_acc,
)
from tests.test_graph import (
    POWER,
    POWER_TOOL,
    RANGE_TOOL,
    SPEED,
    SPEED_LIMIT,
    SPEED_TOOL,
    ScriptedChatModel,
    required_rule,
    tool_call,
)
from tools.server import state as server_state

SPECS = load_tool_specs()
ARG, RULE = required_rule(RANGE_TOOL)
SPEED_ARG, SPEED_RULE = required_rule(SPEED_TOOL)
POWER_ARG, _ = required_rule(POWER_TOOL)
HIGH, LOW = RULE["maximum"], RULE["minimum"]

CASES = [
    {
        "id": "media_001",
        "utt": "끝까지",
        "expected": {"tool": RANGE_TOOL, "args": {ARG: HIGH}},
        "type": "direct",
    },
    {"id": "media_002", "utt": "그거 좀", "expected": {"ask": True}, "type": "missing_arg"},
    {
        "id": "settings_001",
        "utt": "창문 열어",
        "state": {SPEED: SPEED_LIMIT + 20},
        "expected": {"tool": None},
        "type": "unsafe",
    },
    {
        "id": "hvac_001",
        "utt": "에어컨 켜",
        "state": {POWER: "OFF"},
        "expected": {"tool": None},
        "type": "blocked",
    },
    {"id": "none_001", "utt": "졸리다", "expected": {"tool": None}, "type": "no_tool"},
    {
        "id": "media_003",
        "turns": ["그거 좀", "제일 작게"],
        "expected": {"tool": RANGE_TOOL, "args": {ARG: LOW}},
        "type": "multiturn",
    },
    {
        "id": "media_004",
        "utt": "끝까지",
        "expected": {"tool": RANGE_TOOL, "args": {ARG: HIGH}},
        "type": "direct",
    },
]
# 건 순서대로 모델이 내놓을 답. 마지막 건은 일부러 틀린 값을 준다
REPLIES = [
    tool_call(RANGE_TOOL, {ARG: HIGH}),
    tool_call(RANGE_TOOL, {ARG: None}),
    tool_call(SPEED_TOOL, {SPEED_ARG: SPEED_RULE["maximum"]}),
    tool_call(POWER_TOOL, {POWER_ARG: True}),
    AIMessage("잠깐 쉬었다 가세요."),
    tool_call(RANGE_TOOL, {}),
    tool_call(RANGE_TOOL, {ARG: LOW}),
    tool_call(RANGE_TOOL, {ARG: LOW}),
]


@pytest.fixture(scope="module")
def records() -> list[dict]:
    cases = [case | {"file": "test.jsonl"} for case in CASES]
    return asyncio.run(run_cases(ScriptedChatModel(responses=REPLIES), cases))


def test_run_cases_records_actual_and_state(records: list[dict]):
    by_id = {record["id"]: record for record in records}

    assert [record["actual"]["outcome"] for record in records] == [
        "executed",
        "asked",
        "refused",
        "refused",
        "no_tool",
        "executed",
        "executed",
    ]
    done = by_id["media_001"]
    assert done["actual"]["tool"] == RANGE_TOOL
    assert done["actual"]["args"] == {ARG: HIGH}
    assert done["state_after"][SPECS[RANGE_TOOL]["vss"]] == HIGH
    assert len(done["latencies"]) == 1

    unsafe = by_id["settings_001"]
    assert unsafe["state_initial"][SPEED] == SPEED_LIMIT + 20  # 건별 state 가 적용됐다
    assert unsafe["actual"]["tool"] is None
    assert unsafe["actual"]["selected_tool"] == SPEED_TOOL
    assert unsafe["actual"]["code"] == "unsafe_while_driving"
    assert by_id["hvac_001"]["actual"]["code"] == "engine_off"

    multi = by_id["media_003"]
    assert len(multi["latencies"]) == 2
    assert multi["actual"]["args"] == {ARG: LOW}
    # 앞 건의 변경이 다음 건으로 새지 않는다
    assert by_id["media_002"]["state_initial"][SPECS[RANGE_TOOL]["vss"]] != HIGH


def test_on_event_streams_nodes_without_changing_the_record():
    case = CASES[5] | {"file": "test.jsonl"}  # 되묻기 후 값 제공 (두 턴)
    replies = [tool_call(RANGE_TOOL, {}), tool_call(RANGE_TOOL, {ARG: LOW})]
    events: list[dict] = []

    async def run(on_event):
        async with agent_graph(ScriptedChatModel(responses=replies)) as graph:
            return await run_case(graph, case, on_event=on_event)

    plain = asyncio.run(run(None))
    streamed = asyncio.run(run(events.append))

    plain.pop("latencies"), streamed.pop("latencies")
    assert streamed == plain
    assert streamed["actual"]["outcome"] == "executed"
    assert set(streamed) >= {"state_initial", "state_before", "state_after"}
    assert streamed["state_before"] == streamed["state_initial"]  # 되묻기 턴은 상태를 안 바꾼다
    assert streamed["state_after"][SPECS[RANGE_TOOL]["vss"]] == LOW
    assert [(event["turn"], event["node"]) for event in events] == [
        (0, "tool_select"),
        (0, "validate"),
        (0, "respond"),
        (1, "tool_select"),
        (1, "validate"),
        (1, "execute"),
        (1, "respond"),
    ]
    assert events[1]["update"]["trace"]["outcome"] == "asked"
    assert events[-1]["update"]["final_answer"] == streamed["actual"]["final_answer"]


def test_on_event_may_be_async():
    seen: list[str] = []

    async def on_event(event: dict) -> None:
        seen.append(event["node"])

    async def run():
        async with agent_graph(ScriptedChatModel(responses=[AIMessage("네.")])) as graph:
            return await run_case(graph, CASES[4], on_event=on_event)

    record = asyncio.run(run())

    assert seen == ["tool_select", "respond"]
    assert record["file"] == ""  # file 이 없는 건도 받는다
    assert record["actual"]["outcome"] == "no_tool"


def test_run_cases_leaves_server_state_reset(records: list[dict]):
    assert server_state.snapshot() == type(server_state)().snapshot()


def test_scoring_marks_each_case(records: list[dict]):
    rows = {row["id"]: row for row in map(score_record, records)}

    for case_id in ("media_001", "media_002", "settings_001", "hvac_001", "none_001", "media_003"):
        assert rows[case_id]["tool_ok"] and rows[case_id]["arg_ok"] and rows[case_id]["task_ok"], (
            case_id
        )
    wrong = rows["media_004"]  # 도구는 맞고 값이 틀림
    assert wrong["tool_ok"] is True
    assert wrong["arg_ok"] is False
    assert wrong["task_ok"] is False
    assert rows["settings_001"]["domain"] == "settings"


def test_summary_and_markdown(records: list[dict]):
    rows = [score_record(record) for record in records]
    summary = summarize(records, rows)

    assert summary["overall"]["n"] == 7
    assert summary["overall"]["tool_acc"] == 1.0
    assert summary["overall"]["arg_acc"] == pytest.approx(6 / 7)
    assert summary["refusal_rate"] == 1.0
    assert summary["blocked_rate"] == 1.0
    assert summary["by_type"]["direct"]["n"] == 2
    assert summary["by_type"]["direct"]["arg_acc"] == 0.5
    assert summary["latency_p50"] is not None
    markdown = to_markdown(
        "test", summary, rows, {"model": "fake:model", "datasets": ["test.jsonl"]}
    )
    assert "| tool_acc | 100.0% |" in markdown
    assert "media_004" in markdown.split("## 틀린 건")[1]
    assert "media_001" not in markdown.split("## 틀린 건")[1]


def test_tool_acc_and_arg_acc_rules():
    expected = {"tool": RANGE_TOOL, "args": {ARG: HIGH}}

    assert tool_acc(expected, {"tool": RANGE_TOOL})
    assert not tool_acc(expected, {"tool": None})
    assert tool_acc({"ask": True}, {"tool": None})  # 되묻기가 정답이면 실행된 도구가 없어야 한다
    assert arg_acc(expected, {"tool": RANGE_TOOL, "args": {ARG: HIGH, "extra": 1}})
    assert not arg_acc(expected, {"tool": RANGE_TOOL, "args": {ARG: LOW}})
    assert not arg_acc(
        {"tool": RANGE_TOOL}, {"tool": POWER_TOOL, "args": {}}
    )  # 도구가 다르면 인자도 오답
    assert arg_acc({"tool": RANGE_TOOL}, {"tool": RANGE_TOOL, "args": {ARG: LOW}})  # 인자 미지정
    assert arg_acc({"ask": True}, {"tool": None, "ask": True})
    assert not arg_acc({"ask": True}, {"tool": None, "ask": False})
    assert arg_acc({"tool": None}, {"tool": None})
    assert not arg_acc({"tool": None}, {"tool": RANGE_TOOL, "args": {}})


def test_task_success_requires_unchanged_state_when_nothing_should_run(records: list[dict]):
    asked = next(record for record in records if record["id"] == "media_002")
    tampered = asked | {"state_after": asked["state_after"] | {SPECS[RANGE_TOOL]["vss"]: HIGH}}

    assert task_success(asked)
    assert not task_success(tampered)


def test_percentile():
    assert percentile([], 0.5) is None
    assert percentile([1.0], 0.95) == 1.0
    assert percentile([1.0, 2.0, 3.0, 4.0], 0.5) == 2.5
