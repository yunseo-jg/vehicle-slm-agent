"""에이전트 그래프를 실제 모델과 MCP 서버(stdio)로 돌려 보는 데모.

    uv run python scripts/run_graph_demo.py "조수석 창문 내려"
    uv run python scripts/run_graph_demo.py --turns "창문" "반만"
    uv run python scripts/run_graph_demo.py --state Vehicle.Speed=80 "창문 열어"

모델은 .env 의 LLM_PROVIDER(openai | google | ollama) 와 LLM_MODEL 로 고른다.
tools/server.py 를 자식 프로세스로 띄워 MCP 로 도구를 받는다.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402
from langchain_core.messages import HumanMessage  # noqa: E402
from mcp import Client, StdioServerParameters  # noqa: E402

from agent.graph import build_graph  # noqa: E402
from agent.mcp_tools import load_mcp_tools  # noqa: E402

INITIAL_STATE = ROOT / "ontology" / "generated" / "initial_state.json"
SERVER = ROOT / "tools" / "server.py"


def make_llm():
    provider = os.environ.get("LLM_PROVIDER", "").lower()
    model = os.environ.get("LLM_MODEL", "")
    if not provider or not model:
        raise SystemExit(".env 에 LLM_PROVIDER 와 LLM_MODEL 을 넣어 주세요 (.env.example 참고)")
    try:
        if provider == "openai":
            from langchain_openai import ChatOpenAI

            return ChatOpenAI(model=model, temperature=0)
        if provider == "google":
            from langchain_google_genai import ChatGoogleGenerativeAI

            return ChatGoogleGenerativeAI(model=model, temperature=0)
        if provider == "ollama":
            from langchain_ollama import ChatOllama

            return ChatOllama(model=model, temperature=0, base_url=os.environ.get("OLLAMA_HOST"))
    except ImportError as error:
        extra = "local" if provider == "ollama" else "cloud"
        raise SystemExit(
            f"{error.name} 가 없습니다. `uv sync --extra {extra}` 후 다시 실행"
        ) from error
    raise SystemExit(f"LLM_PROVIDER 는 openai | google | ollama 중 하나여야 합니다: {provider!r}")


def parse_state(pairs: list[str]) -> dict:
    """Vehicle.Speed=80 → {"Vehicle.Speed": 80}. 값은 JSON 으로 읽고, 안 되면 문자열."""
    overrides = {}
    for pair in pairs:
        key, sep, raw = pair.partition("=")
        if not sep:
            raise SystemExit(f"--state 는 키=값 형식입니다: {pair!r}")
        try:
            overrides[key] = json.loads(raw)
        except json.JSONDecodeError:
            overrides[key] = raw
    return overrides


async def run(turns: list[str], overrides: dict) -> None:
    llm = make_llm()  # 설정이 빠졌으면 서버를 띄우기 전에 끝낸다
    vehicle_state = json.loads(INITIAL_STATE.read_text(encoding="utf-8"))
    unknown = sorted(set(overrides) - set(vehicle_state))
    if unknown:
        raise SystemExit(f"초기 상태에 없는 키입니다: {unknown}")
    vehicle_state.update(overrides)

    # 서버 쪽 시뮬레이터도 같은 상태에서 시작하게 한다
    env = dict(os.environ) | {"VEHICLE_STATE_OVERRIDES": json.dumps(overrides)}
    server = StdioServerParameters(command=sys.executable, args=[str(SERVER)], env=env)
    config = {"configurable": {"thread_id": "demo"}}
    async with Client(server) as client:
        graph = build_graph(llm, await load_mcp_tools(client))
        for utterance in turns:
            result = await graph.ainvoke(
                {"messages": [HumanMessage(utterance)], "vehicle_state": vehicle_state}, config
            )
            tool_result = result.get("tool_result")
            if tool_result and tool_result["status"] == "ok":
                vehicle_state.update(tool_result["state_after"])  # 다음 턴에 넘길 현재 상태
            print(f"발화          {utterance}")
            print(f"trace         {json.dumps(result['trace'], ensure_ascii=False)}")
            print(f"tool_call     {json.dumps(result.get('tool_call'), ensure_ascii=False)}")
            print(f"tool_result   {json.dumps(tool_result, ensure_ascii=False)}")
            print(f"final_answer  {result['final_answer']}")
            print()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("utterance", nargs="?", help="발화 한 개")
    parser.add_argument(
        "--turns", nargs="+", metavar="발화", help="같은 대화에서 순서대로 넣을 발화들"
    )
    parser.add_argument(
        "--state", action="append", default=[], metavar="키=값", help="시작 상태 덮어쓰기"
    )
    args = parser.parse_args()
    turns = args.turns or ([args.utterance] if args.utterance else [])
    if not turns or (args.turns and args.utterance):
        parser.error("발화 하나 또는 --turns 중 하나만 주세요")
    load_dotenv(ROOT / ".env")
    asyncio.run(run(turns, parse_state(args.state)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
