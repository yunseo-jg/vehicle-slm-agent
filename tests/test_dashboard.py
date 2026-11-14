"""dashboard/server.py 테스트. 실제 LLM 없이 가짜 모델로 돈다 (tests/test_eval.py 와 같은 방식)."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, HumanMessage

from agent.graph import load_tool_specs
from dashboard.server import create_app, to_jsonable
from tests.test_graph import RANGE_TOOL, SPEED, ScriptedChatModel, required_rule, tool_call

SPECS = load_tool_specs()
ARG, RULE = required_rule(RANGE_TOOL)
HIGH = RULE["maximum"]
PATH = SPECS[RANGE_TOOL]["vss"]
CASE = {
    "id": "media_901",
    "utt": "끝까지",
    "expected": {"tool": RANGE_TOOL, "args": {ARG: HIGH}},
    "type": "direct",
}


def make_client(tmp_path, replies: list) -> TestClient:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "media.jsonl").write_text(json.dumps(CASE, ensure_ascii=False) + "\n", "utf-8")
    app = create_app(
        llm_factory=lambda model: ScriptedChatModel(responses=replies),
        resolve_model=lambda model=None: model or "fake:model",
        data_dir=data_dir,
        review_dir=tmp_path / "review",
    )
    return TestClient(app)


def run(client: TestClient, body: dict) -> list[tuple[str, dict]]:
    """POST /api/run 의 SSE 를 (이벤트 이름, 데이터) 목록으로."""
    events = []
    with client.stream("POST", "/api/run", json=body) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        name = None
        for line in response.iter_lines():
            if line.startswith("event: "):
                name = line[len("event: ") :]
            elif line.startswith("data: "):
                events.append((name, json.loads(line[len("data: ") :])))
    return events


def test_meta_and_cases(tmp_path):
    with make_client(tmp_path, [AIMessage("네.")]) as client:
        meta = client.get("/api/meta").json()
        cases = client.get("/api/cases").json()

    assert {tool["name"] for tool in meta["tools"]} == set(SPECS)
    assert meta["initial_state"][SPEED] == 0
    assert meta["model"] == {"id": "fake:model", "ready": True, "error": None}
    assert "zone" in meta["instance_map"]
    assert cases == [CASE | {"file": "media.jsonl", "domain": "media"}]


def test_run_streams_nodes_then_scored_record(tmp_path):
    with make_client(tmp_path, [tool_call(RANGE_TOOL, {ARG: HIGH})]) as client:
        events = run(client, {"file": "media.jsonl", "id": "media_901"})

    names = [name for name, _ in events]
    assert names == ["start", "node", "node", "node", "node", "result"]
    assert [data["node"] for name, data in events if name == "node"] == [
        "tool_select",
        "validate",
        "execute",
        "respond",
    ]
    assert all(data["turn"] == 0 for name, data in events if name == "node")
    # 메시지 객체는 역할·내용·tool_calls 만 남은 dict 로 온다
    respond = events[4][1]["update"]
    assert respond["messages"][0] == {
        "role": "ai",
        "content": "",
        "tool_calls": [{"name": RANGE_TOOL, "args": {ARG: HIGH}}],
    }
    result = events[-1][1]
    record = result["record"]
    assert events[0][1]["run_id"] == result["run_id"]
    assert record["actual"]["outcome"] == "executed"
    assert record["state_initial"][PATH] != HIGH
    assert record["state_after"][PATH] == HIGH
    assert result["score"]["tool_ok"] and result["score"]["arg_ok"] and result["score"]["task_ok"]
    assert result["model"] == "fake:model"


def test_adhoc_run_applies_state_and_skips_scoring(tmp_path):
    replies = [tool_call(RANGE_TOOL, {}), tool_call(RANGE_TOOL, {ARG: HIGH})]
    with make_client(tmp_path, replies) as client:
        events = run(client, {"turns": ["그거 좀", "끝까지"], "state": {SPEED: 30}})
        unknown = client.post("/api/run", json={"turns": ["창문"], "state": {"Vehicle.Nope": 1}})
        empty = client.post("/api/run", json={"turns": ["  "]})

    result = events[-1][1]
    assert result["score"] is None
    assert result["record"]["id"].startswith("adhoc_")
    assert result["record"]["state_initial"][SPEED] == 30
    assert [data["turn"] for name, data in events if name == "node"] == [0, 0, 0, 1, 1, 1, 1]
    assert result["record"]["actual"]["outcome"] == "executed"
    assert unknown.status_code == 400
    assert empty.status_code == 400


def test_findings_and_candidates_are_appended_per_reviewer(tmp_path):
    replies = [tool_call(RANGE_TOOL, {ARG: HIGH}), tool_call(RANGE_TOOL, {})]
    with make_client(tmp_path, replies) as client:
        first = run(client, {"file": "media.jsonl", "id": "media_901"})[-1][1]
        adhoc = run(client, {"turns": ["그거 좀"], "state": {SPEED: 30}})[-1][1]
        body = {
            "reviewer": "윤서",
            "run_id": first["run_id"],
            "category": "expected",
            "memo": "애매함",
        }
        saved = client.post("/api/findings", json=body)
        client.post("/api/findings", json=body | {"run_id": adhoc["run_id"], "category": "code"})
        draft = client.post("/api/candidates", json={"reviewer": "윤서", "run_id": adhoc["run_id"]})
        bad_category = client.post("/api/findings", json=body | {"category": "etc"})
        no_name = client.post("/api/findings", json=body | {"reviewer": " ../ "})
        no_run = client.post("/api/findings", json=body | {"run_id": "nope"})

    assert saved.status_code == 200
    lines = [
        json.loads(line)
        for line in (tmp_path / "review" / "findings_윤서.jsonl").read_text("utf-8").splitlines()
    ]
    assert len(lines) == 2
    finding = lines[0]
    assert finding["case_id"] == "media_901"
    assert finding["category"] == "expected"
    assert finding["memo"] == "애매함"
    assert finding["model"] == "fake:model"
    assert finding["expected"] == CASE["expected"]
    assert finding["actual"] == {"tool": RANGE_TOOL, "args": {ARG: HIGH}, "ask": False}
    assert finding["trace"]["outcome"] == "executed"
    assert finding["final_answer"]
    assert lines[1]["case_id"] is None and lines[1]["state"] == {SPEED: 30}
    assert lines[1]["trace"]["outcome"] == "asked"

    candidate = json.loads((tmp_path / "review" / "candidates_윤서.jsonl").read_text("utf-8"))
    assert draft.json()["line"] == candidate
    assert candidate["utt"] == "그거 좀"
    assert candidate["state"] == {SPEED: 30}
    assert candidate["expected"] == {"ask": True}
    assert candidate["type"] == "missing_arg"
    assert candidate["id"].startswith(f"{SPECS[RANGE_TOOL]['domain']}_cand_")
    assert (bad_category.status_code, no_name.status_code, no_run.status_code) == (400, 400, 404)


def test_model_can_be_switched_and_failure_is_reported(tmp_path):
    def factory(model: str):
        if model == "fake:broken":
            raise SystemExit("패키지가 없습니다")
        return ScriptedChatModel(responses=[AIMessage("네.")])

    app = create_app(
        llm_factory=factory,
        resolve_model=lambda model=None: model or "fake:broken",
        data_dir=tmp_path / "data",
        review_dir=tmp_path / "review",
    )
    with TestClient(app) as client:
        # 시작할 때 모델을 못 만들어도 서버는 뜨고, 사유를 알려 준다
        assert client.get("/api/meta").json()["model"] == {
            "id": "fake:broken",
            "ready": False,
            "error": "패키지가 없습니다",
        }
        assert client.post("/api/run", json={"turns": ["창문"]}).status_code == 503
        switched = client.post("/api/model", json={"model": "fake:ok"}).json()
        assert switched == {"id": "fake:ok", "ready": True, "error": None}
        assert run(client, {"turns": ["안녕"]})[-1][0] == "result"
        assert client.post("/api/model", json={"model": "fake:broken"}).json()["ready"] is False


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (HumanMessage("안녕"), {"role": "human", "content": "안녕"}),
        ({"a": (1, None)}, {"a": [1, None]}),
        (object, str(object)),
    ],
)
def test_to_jsonable(value, expected):
    assert to_jsonable(value) == expected
