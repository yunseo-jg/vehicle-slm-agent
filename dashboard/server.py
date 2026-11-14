"""검수용 로컬 대시보드 서버.

    make dashboard          # http://localhost:8000

실행과 채점은 eval/run_eval.py 의 run_case, eval/score.py 의 score_record 를 그대로 부른다.
그래서 화면 결과와 명령줄 결과가 같다. 여기서 하는 일은 그 결과를 화면으로 보내고,
검수 기록을 eval/review/ 아래 파일에 한 줄씩 쌓는 것뿐이다.

API
  GET  /api/meta        도구 목록, 초기 상태, instance_map, 고정 문장, 현재 모델
  GET  /api/cases       평가셋 전체 (파일명, 유형, 도메인 포함)
  POST /api/model       모델 바꾸기 {"model": "openai:gpt-4o-mini"}
  POST /api/run         한 건 실행. SSE 로 start → node... → result (또는 error)
  POST /api/findings    검수 기록 한 줄 → eval/review/findings_<이름>.jsonl
  POST /api/candidates  평가셋 형식 초안 한 줄 → eval/review/candidates_<이름>.jsonl
"""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from collections import OrderedDict
from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from langchain_core.messages import BaseMessage
from pydantic import BaseModel

from agent.graph import load_tool_specs
from agent.llm import make_llm, resolve_model_id
from agent.prompts import DOMAIN_LABELS, ERROR_FALLBACK, ERROR_MESSAGES
from eval.run_eval import agent_graph, load_cases, run_case
from eval.score import score_record
from ontology.build_schema import load_ontology

ROOT = Path(__file__).resolve().parent.parent
INDEX = Path(__file__).resolve().parent / "index.html"
DATA_DIR = ROOT / "eval" / "data"
REVIEW_DIR = ROOT / "eval" / "review"
INITIAL_STATE = ROOT / "ontology" / "generated" / "initial_state.json"

CATEGORIES = {
    "candidate": "평가셋 추가 후보",
    "expected": "정답 기준 이의",
    "code": "코드·프롬프트 문제",
}
KEPT_RUNS = 500  # 검수 기록을 남길 수 있게 기억해 두는 최근 실행 수


class ModelRequest(BaseModel):
    model: str


class RunRequest(BaseModel):
    file: str | None = None
    id: str | None = None
    turns: list[str] | None = None
    state: dict[str, Any] | None = None


class FindingRequest(BaseModel):
    reviewer: str
    run_id: str
    category: str
    memo: str = ""


class CandidateRequest(BaseModel):
    reviewer: str
    run_id: str


def to_jsonable(value: Any) -> Any:
    """화면으로 보낼 수 있는 값으로. LangChain 메시지는 역할, 내용, tool_calls 만 남긴다."""
    if isinstance(value, BaseMessage):
        content = value.content if isinstance(value.content, str) else str(value.content)
        message: dict[str, Any] = {"role": value.type, "content": content}
        calls = getattr(value, "tool_calls", None)
        if calls:
            message["tool_calls"] = [{"name": c["name"], "args": c["args"]} for c in calls]
        return message
    if isinstance(value, dict):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [to_jsonable(item) for item in value]
    if value is None or isinstance(value, str | int | float | bool):
        return value
    return str(value)


def sse(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(to_jsonable(data), ensure_ascii=False)}\n\n"


class Runner:
    """그래프를 쥐고 요청을 한 번에 하나씩 처리하는 작업자.

    agent_graph 는 들어간 태스크에서 나와야 해서, 모델 교체와 실행을 모두 이 태스크 하나가 한다.
    큐가 하나라 두 건이 동시에 실행되지 않고, 시뮬레이터 상태가 섞이지 않는다.
    """

    def __init__(self, llm_factory: Callable[[str], Any], resolve_model: Callable[..., str]):
        self.llm_factory = llm_factory
        self.resolve_model = resolve_model
        self.model: str | None = None
        self.error: str | None = None
        self.ready = False
        self._queue: asyncio.Queue | None = None
        self._task: asyncio.Task | None = None

    async def start(self, model: str | None = None) -> None:
        self._queue = asyncio.Queue()
        started = asyncio.get_running_loop().create_future()
        self._task = asyncio.create_task(self._main(model, started))
        await started

    async def stop(self) -> None:
        await self._submit("stop", None)
        await self._task

    async def set_model(self, model: str) -> None:
        await self._submit("model", model)

    async def run(self, case: dict, on_event: Callable[[dict], None]) -> dict:
        return await self._submit("run", (case, on_event))

    async def _submit(self, kind: str, payload: Any) -> Any:
        done = asyncio.get_running_loop().create_future()
        await self._queue.put((kind, payload, done))
        return await done

    def status(self) -> dict:
        return {"id": self.model, "ready": self.ready, "error": self.error}

    async def _main(self, model: str | None, prepared: asyncio.Future) -> None:
        while True:
            llm = self._prepare(model)
            if llm is None:
                prepared.set_result(None)
                next_model = await self._serve(None)
            else:
                async with agent_graph(llm) as graph:
                    self.ready = True
                    prepared.set_result(None)
                    next_model = await self._serve(graph)
                self.ready = False
            if next_model is None:
                return
            model, prepared = next_model

    def _prepare(self, model: str | None):
        """모델을 만든다. 설정이 빠졌거나 패키지가 없으면 None 을 주고 사유를 error 에 남긴다."""
        self.ready, self.error = False, None
        try:
            self.model = self.resolve_model(model)
            return self.llm_factory(self.model)
        except (SystemExit, Exception) as error:  # noqa: BLE001  make_llm 은 SystemExit 으로 알린다
            self.model = model or self.model
            self.error = str(error) or type(error).__name__
            return None

    async def _serve(self, graph) -> tuple[str, asyncio.Future] | None:
        """요청을 처리한다.

        모델을 바꾸라는 요청이 오면 (모델, 완료 신호) 를, 종료면 None 을 준다.
        """
        while True:
            kind, payload, done = await self._queue.get()
            if kind == "stop":
                done.set_result(None)
                return None
            if kind == "model":
                return payload, done
            if graph is None:
                done.set_exception(RuntimeError(self.error or "모델이 준비되지 않았습니다"))
                continue
            case, on_event = payload
            try:
                done.set_result(await run_case(graph, case, on_event=on_event))
            except Exception as error:  # noqa: BLE001  한 건의 실패가 작업자를 죽이지 않게
                done.set_exception(error)


def _safe_name(name: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z가-힣_-]", "", name.strip())
    if not cleaned:
        raise HTTPException(400, "이름을 먼저 입력해 주세요 (한글, 영문, 숫자만)")
    return cleaned


def _append_line(path: Path, line: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(line, ensure_ascii=False) + "\n")


def _shown(path: Path) -> str:
    return str(path.relative_to(ROOT) if path.is_relative_to(ROOT) else path)


def _trace(actual: dict) -> dict:
    return {
        "selected_tool": actual.get("selected_tool"),
        "selected_args": actual.get("selected_args"),
        "executed_tool": actual.get("tool"),
        "outcome": actual.get("outcome"),
        "code": actual.get("code"),
    }


def _draft_case(run: dict, specs: dict[str, dict]) -> dict:
    """실행 결과로 평가셋 한 줄의 초안을 만든다. expected 와 type 은 실제 동작에서 채운 추정값."""
    record, actual = run["record"], run["record"]["actual"]
    outcome, code = actual.get("outcome"), actual.get("code")
    if outcome == "executed":
        expected: dict = {"tool": actual["tool"], "args": actual.get("args") or {}}
    elif outcome == "asked":
        expected = {"ask": True}
    else:
        expected = {"tool": None}
    if len(record["turns"]) > 1:
        kind = "multiturn"
    elif outcome == "asked":
        kind = "missing_arg"
    elif code == "unsafe_while_driving":
        kind = "unsafe"
    elif code == "engine_off":
        kind = "blocked"
    else:
        kind = "direct" if outcome == "executed" else "no_tool"
    domain = specs.get(actual.get("selected_tool") or "", {}).get("domain", "none")
    draft: dict = {"id": f"{domain}_cand_{datetime.now():%m%d%H%M%S}"}
    if len(record["turns"]) > 1:
        draft["turns"] = record["turns"]
    else:
        draft["utt"] = record["turns"][0]
    if run["case"].get("state"):
        draft["state"] = run["case"]["state"]
    return draft | {"expected": expected, "type": kind}


def create_app(
    llm_factory: Callable[[str], Any] = make_llm,
    resolve_model: Callable[..., str] = resolve_model_id,
    data_dir: Path = DATA_DIR,
    review_dir: Path = REVIEW_DIR,
) -> FastAPI:
    runner = Runner(llm_factory, resolve_model)
    runs: OrderedDict[str, dict] = OrderedDict()
    specs = load_tool_specs()
    initial_state = json.loads(INITIAL_STATE.read_text(encoding="utf-8"))
    background: set[asyncio.Task] = set()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        load_dotenv(ROOT / ".env")
        await runner.start()
        yield
        await runner.stop()

    app = FastAPI(title="vehicle-slm-agent 검수 대시보드", lifespan=lifespan)

    def cases() -> list[dict]:
        loaded = load_cases([str(path) for path in sorted(data_dir.glob("*.jsonl"))])
        return [case | {"domain": case["id"].rsplit("_", 1)[0]} for case in loaded]

    def find_run(run_id: str) -> dict:
        if run_id not in runs:
            raise HTTPException(404, "실행 기록을 찾지 못했습니다. 다시 실행한 뒤 저장해 주세요")
        return runs[run_id]

    def build_case(request: RunRequest) -> dict:
        if request.id:
            for case in cases():
                if case["id"] == request.id and request.file in (None, case["file"]):
                    return case
            raise HTTPException(404, f"평가셋에 없는 건입니다: {request.file} {request.id}")
        turns = [turn.strip() for turn in request.turns or [] if turn.strip()]
        if not turns:
            raise HTTPException(400, "발화를 입력해 주세요")
        state = request.state or {}
        unknown = sorted(set(state) - set(initial_state))
        if unknown:
            raise HTTPException(400, f"초기 상태에 없는 키입니다: {unknown}")
        adhoc_id = f"adhoc_{datetime.now():%H%M%S}_{uuid.uuid4().hex[:4]}"
        return {
            "id": adhoc_id,
            "file": "",
            "type": "adhoc",
            "domain": "adhoc",
            "turns": turns,
            "state": state,
            "expected": None,  # 정답이 없는 건. 채점하지 않는다
        }

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(INDEX, headers={"Cache-Control": "no-store"})

    @app.get("/api/meta")
    async def meta() -> dict:
        return {
            "tools": list(specs.values()),
            "initial_state": initial_state,
            "instance_map": load_ontology()["instance_map"],
            "error_messages": ERROR_MESSAGES | {"": ERROR_FALLBACK},
            "domain_labels": DOMAIN_LABELS,
            "categories": CATEGORIES,
            "model": runner.status(),
            "review_dir": _shown(review_dir),
        }

    @app.get("/api/cases")
    async def list_cases() -> list[dict]:
        return cases()

    @app.post("/api/model")
    async def set_model(request: ModelRequest) -> dict:
        await runner.set_model(request.model.strip())
        return runner.status()

    @app.post("/api/run")
    async def run(request: RunRequest) -> StreamingResponse:
        case = build_case(request)
        if not runner.ready:
            raise HTTPException(503, runner.error or "모델을 준비하는 중입니다")
        run_id = uuid.uuid4().hex[:12]
        events: asyncio.Queue = asyncio.Queue()

        async def work() -> None:
            try:
                record = await runner.run(case, lambda event: events.put_nowait(("node", event)))
            except Exception as error:  # noqa: BLE001
                events.put_nowait(("error", {"message": f"{type(error).__name__}: {error}"}))
                return
            record = to_jsonable(record)
            score = score_record(record) if isinstance(case.get("expected"), dict) else None
            runs[run_id] = {"case": case, "record": record, "score": score, "model": runner.model}
            while len(runs) > KEPT_RUNS:
                runs.popitem(last=False)
            result = {"run_id": run_id, "record": record, "score": score, "model": runner.model}
            events.put_nowait(("result", result))

        task = asyncio.create_task(work())  # 화면이 닫혀도 실행은 끝까지 간다
        background.add(task)
        task.add_done_callback(background.discard)

        async def stream():
            yield sse("start", {"run_id": run_id, "case": case, "model": runner.model})
            while True:
                kind, data = await events.get()
                yield sse(kind, data)
                if kind in ("result", "error"):
                    return

        headers = {"Cache-Control": "no-store", "X-Accel-Buffering": "no"}
        return StreamingResponse(stream(), media_type="text/event-stream", headers=headers)

    @app.post("/api/findings")
    async def add_finding(request: FindingRequest) -> dict:
        if request.category not in CATEGORIES:
            raise HTTPException(400, f"분류는 {list(CATEGORIES)} 중 하나여야 합니다")
        name = _safe_name(request.reviewer)
        run = find_run(request.run_id)
        record, actual = run["record"], run["record"]["actual"]
        line = {
            "time": datetime.now().isoformat(timespec="seconds"),
            "reviewer": name,
            "category": request.category,
            "category_label": CATEGORIES[request.category],
            "memo": request.memo.strip(),
            "model": run["model"],
            "case_id": None if run["case"]["type"] == "adhoc" else record["id"],
            "file": record["file"] or None,
            "turns": record["turns"],
            "state": run["case"].get("state") or {},
            "expected": record["expected"],
            "actual": {key: actual.get(key) for key in ("tool", "args", "ask")},
            "trace": _trace(actual),
            "final_answer": actual.get("final_answer", ""),
        }
        path = review_dir / f"findings_{name}.jsonl"
        _append_line(path, line)
        return {"saved": _shown(path)}

    @app.post("/api/candidates")
    async def add_candidate(request: CandidateRequest) -> dict:
        name = _safe_name(request.reviewer)
        run = find_run(request.run_id)
        draft = _draft_case(run, specs) | {
            "draft": {
                "note": "초안. expected 와 type 은 실제 동작에서 채운 값이라 사람이 확인해야 한다",
                "by": name,
                "model": run["model"],
                "time": datetime.now().isoformat(timespec="seconds"),
            }
        }
        path = review_dir / f"candidates_{name}.jsonl"
        _append_line(path, draft)
        return {"saved": _shown(path), "line": draft}

    return app


app = create_app()
