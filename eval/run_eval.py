"""평가셋을 에이전트에 넣고 선택·실행된 도구, 인자, 소요시간을 기록한다.

    uv run python eval/run_eval.py --dataset eval/data/*.jsonl --model openai:gpt-4o-mini
    uv run python eval/run_eval.py --dataset eval/data/sample.jsonl          # 모델은 .env 에서

--model 은 provider:model (openai | google | ollama). 생략하면 .env 의 LLM_PROVIDER, LLM_MODEL.

출력
  eval/runs/<timestamp>_<model>.jsonl      한 줄에 한 건 (입력 + actual + 상태 + latency)
  eval/runs/<timestamp>_<model>.meta.json  모델, 평가셋, 커밋 해시 등 리포트에 적을 조건
jsonl 을 score.py 에 넘긴다.

도구는 tools/server.py 의 MCP 서버에 in-process 로 붙어서 부른다. 건마다 시뮬레이터를
초기 상태로 되돌리고 그 건의 state 를 덮어쓴다. 멀티턴은 turns 를 같은 대화에 순서대로 넣고
마지막 턴의 결과를 actual 로 남긴다.

다른 코드에서 쓸 때 (대시보드 등)
    async with agent_graph(llm) as graph:
        record = await run_case(graph, case, on_event=...)   # 한 건 실행
    row = eval.score.score_record(record)                    # 한 건 채점
"""

from __future__ import annotations

import argparse
import asyncio
import inspect
import json
import re
import subprocess
import sys
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402
from langchain_core.messages import HumanMessage  # noqa: E402
from mcp import Client  # noqa: E402

from agent.graph import build_graph  # noqa: E402
from agent.llm import make_llm, resolve_model_id  # noqa: E402
from agent.mcp_tools import load_mcp_tools  # noqa: E402
from tools.server import mcp  # noqa: E402
from tools.server import state as server_state  # noqa: E402

RUNS_DIR = ROOT / "eval" / "runs"


def load_cases(paths: list[str], limit: int | None = None) -> list[dict]:
    """jsonl 여러 개를 읽는다. 파일 간 id 가 겹칠 수 있어서 건마다 file 을 붙인다."""
    cases = []
    for path in paths:
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            if line.strip():
                cases.append(json.loads(line) | {"file": Path(path).name})
    return cases[:limit] if limit else cases


@asynccontextmanager
async def agent_graph(llm):
    """MCP 서버에 in-process 로 붙은 에이전트 그래프. 나갈 때 시뮬레이터를 초기 상태로 되돌린다.

    async with agent_graph(llm) as graph:
        record = await run_case(graph, case)
    """
    try:
        async with Client(mcp) as client:
            yield build_graph(llm, await load_mcp_tools(client))
    finally:
        server_state.reset()


async def run_case(graph, case: dict, thread_id: str | None = None, on_event=None) -> dict:
    """한 건을 돌려 기록 한 줄을 만든다. 예외가 나도 기록으로 남긴다.

    case 는 평가셋 한 줄(dict). graph 는 agent_graph() 로 얻는다.
    on_event 를 주면 노드가 끝날 때마다 {"turn": 턴 번호(0부터), "node": 노드 이름,
    "update": 그 노드가 바꾼 상태} 를 넘긴다 (동기·비동기 함수 모두 가능). 최종 기록은
    on_event 유무와 관계없이 같다.

    기록의 상태 스냅샷 (전체 상태 dict)
      state_initial  건의 state 를 덮어쓴 직후, 첫 턴 전
      state_before   마지막 턴 직전 (한 턴짜리면 state_initial 과 같다)
      state_after    마지막 턴이 끝난 뒤
    """
    server_state.reset()
    for key, value in case.get("state", {}).items():
        server_state.set(key, value)
    turns = case.get("turns") or [case["utt"]]
    record = {"file": case.get("file", ""), "id": case["id"], "type": case["type"]}
    record |= {"expected": case["expected"], "turns": turns}
    record["state_initial"] = before = server_state.snapshot()
    thread_id = thread_id or f"{case['id']}:{uuid.uuid4().hex[:8]}"
    config = {"configurable": {"thread_id": thread_id}}
    latencies, result = [], None
    try:
        for turn, utterance in enumerate(turns):
            before = server_state.snapshot()
            payload = {"messages": [HumanMessage(utterance)], "vehicle_state": before}
            started = time.perf_counter()
            result = await _run_turn(graph, payload, config, turn, on_event)
            latencies.append(round(time.perf_counter() - started, 3))
    except Exception as error:  # noqa: BLE001  API 오류 등. 그 건만 실패로 남긴다
        record["error"] = f"{type(error).__name__}: {error}"
        result = None
    return record | {
        "latencies": latencies,
        "state_before": before,
        "state_after": server_state.snapshot(),
        "actual": _actual(result),
    }


async def _run_turn(graph, payload: dict, config: dict, turn: int, on_event) -> dict:
    """한 턴을 돌리고 그래프의 최종 상태를 돌려준다."""
    if on_event is None:
        return await graph.ainvoke(payload, config)
    async for chunk in graph.astream(payload, config, stream_mode="updates"):
        for node, update in chunk.items():
            handled = on_event({"turn": turn, "node": node, "update": update})
            if inspect.isawaitable(handled):
                await handled
    return (await graph.aget_state(config)).values


def _actual(result: dict | None) -> dict:
    """마지막 턴의 결과. tool 은 실제로 실행된 도구 (검증에서 막혔거나 되물었으면 None)."""
    if result is None:
        return {"tool": None, "args": None, "ask": False, "outcome": "error", "code": None}
    trace = result["trace"]
    call = result.get("tool_call") or {}
    executed = trace["executed_tool"]
    return {
        "tool": executed,
        "args": call.get("args") if executed else None,
        "ask": trace["outcome"] == "asked",
        "outcome": trace["outcome"],
        "code": trace["code"],
        "selected_tool": trace["selected_tool"],
        "selected_args": call.get("args"),
        "final_answer": result.get("final_answer", ""),
    }


async def run_cases(llm, cases: list[dict], on_record=None) -> list[dict]:
    """모든 건을 순서대로 돌린다 (latency 를 재려고 동시에 돌리지 않는다)."""
    records = []
    async with agent_graph(llm) as graph:
        for index, case in enumerate(cases):
            record = await run_case(graph, case, thread_id=f"{index}:{case['id']}")
            records.append(record)
            if on_record:
                on_record(index, record)
    return records


def _git_commit() -> str:
    done = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return done.stdout.strip() or "unknown"


def main() -> int:
    parser = argparse.ArgumentParser(description="평가셋을 에이전트에 넣고 결과를 기록한다")
    parser.add_argument("--dataset", required=True, nargs="+", help="평가셋 jsonl (여러 개 가능)")
    parser.add_argument("--model", default=None, help="provider:model. 생략하면 .env 에서")
    parser.add_argument("--limit", type=int, default=None, help="앞에서부터 N 건만")
    parser.add_argument("--out", default=None, help="결과 jsonl 경로 (기본: eval/runs/ 아래)")
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    model_id = resolve_model_id(args.model)
    llm = make_llm(model_id)
    cases = load_cases(args.dataset, args.limit)

    started = datetime.now()
    stem = f"{started:%Y%m%d_%H%M%S}_{re.sub(r'[^A-Za-z0-9._-]+', '-', model_id)}"
    out = Path(args.out) if args.out else RUNS_DIR / f"{stem}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)

    def progress(index: int, record: dict) -> None:
        actual = record["actual"]
        shown = actual["tool"] or actual.get("selected_tool") or "-"
        print(
            f"[{index + 1}/{len(cases)}] {record['id']:14} {actual['outcome']:9} {shown}",
            flush=True,
        )

    with out.open("w", encoding="utf-8") as file:

        def write(index: int, record: dict) -> None:
            file.write(json.dumps(record, ensure_ascii=False) + "\n")
            file.flush()
            progress(index, record)

        records = asyncio.run(run_cases(llm, cases, on_record=write))

    meta = {
        "model": model_id,
        "temperature": 0,
        "datasets": sorted({case["file"] for case in cases}),
        "cases": len(records),
        "errors": sum("error" in record for record in records),
        "commit": _git_commit(),
        "started_at": started.isoformat(timespec="seconds"),
        "seconds": round((datetime.now() - started).total_seconds(), 1),
    }
    out.with_suffix(".meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    shown = out.relative_to(ROOT) if out.is_relative_to(ROOT) else out
    print(f"\n{len(records)}건 기록: {shown}")
    print(f"채점: uv run python eval/score.py {shown}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
