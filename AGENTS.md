# AGENTS.md

AI 코딩 도구(Cursor, Claude Code, Codex, Copilot 등)가 이 레포에서 작업할 때 읽는 파일.
사람이 읽어도 된다. 사람용 규칙은 CONTRIBUTING.md에 있고, 여기는 도구가 실수하지 않게 하는 내용 위주.

## 프로젝트 한 줄

온디바이스 SLM 기반 tool-calling 에이전트. 차량 도메인. 사용자 발화 → LangGraph 에이전트 → MCP 도구 서버 → 차량 시뮬레이터.
클라우드 모델로 만들고 로컬 SLM(Ollama)으로 교체한 뒤 같은 평가셋으로 비교한다.

## 스택

- Python 3.11+, uv, ruff, pytest
- LangGraph, langchain-mcp-adapters, MCP Python SDK 2.x (`mcp.server.mcpserver.MCPServer`. 1.x의 FastMCP 아님), PyYAML, Pydantic
- 로컬 모델: Ollama. 트레이싱: Langfuse
- 차량 신호 이름: COVESA VSS 6.0

## 폴더 역할 (파일을 만들 위치)

| 경로 | 넣는 것 | 넣지 않는 것 |
|------|---------|-------------|
| `ontology/vehicle.yaml` | 기능 정의. 도구 스키마의 유일한 원천 | 코드 |
| `ontology/build_schema.py` | yaml → `generated/tools.json`, `generated/initial_state.json` | 도구 구현 |
| `ontology/generated/` | 생성물. 손으로 편집 금지 | |
| `tools/server.py` | MCP 서버 진입점 | 도메인 로직 |
| `tools/<domain>.py` | 도메인별 도구 구현 (hvac, media, nav, phone, status) | 상태 저장 |
| `sim/state.py` | 차량 상태 dict, get/set, precondition 검사 | 도구 정의 |
| `agent/graph.py` | LangGraph 노드·엣지 | 프롬프트 문자열 |
| `agent/prompts.py` | 시스템 프롬프트, few-shot | |
| `eval/data/*.jsonl` | 평가셋 | 원본 데이터 |
| `eval/run_eval.py`, `eval/score.py` | 실행기, 채점기 | |
| `reports/` | 실험 결과 md, csv | 코드 |
| `training/` | LoRA 데이터 합성, 학습 스크립트·노트북 | 모델 가중치 |
| `data/raw/` | 로컬 전용. 커밋 금지 | |
| `tests/` | pytest | |
| `scripts/` | 일회성 스크립트 | 재사용 모듈 |

## 명령

```bash
uv sync                 # 의존성
make schema             # 온톨로지 → 생성물
make test               # pytest
make lint               # ruff check + format --check
make server             # MCP 서버 stdio 실행
make eval               # 평가 실행 (eval/run_eval.py)
make validate-eval      # 평가셋과 온톨로지 대조
```

코드를 바꿨으면 `make lint && make test`가 통과하는지 확인하고 끝낸다.

## 지켜야 하는 것

1. 도구 스키마를 코드에 직접 쓰지 않는다. `ontology/vehicle.yaml`을 고치고 `make schema`를 돌린다.
2. 시뮬레이터 상태 키는 VSS 경로 문자열 그대로. 예: `Vehicle.Cabin.HVAC.Station.Row1.Driver.Temperature`. 새 키 이름을 지어내지 않는다.
3. VSS 경로는 지어내지 않는다. 확신이 없으면 `ontology/vss_ref.md` 또는 `data/raw/vss.json`(6.0)에서 확인하고, 없으면 그렇다고 말한다.
4. 도구 함수 반환은 항상 `{"status": "ok"|"error", "code": str|None, "state_after": dict}`.
5. 안전 검사(주행 중 금지, 범위, precondition)는 모델이 아니라 코드에서 한다. `sim/state.py`의 검사 함수를 쓴다.
6. 에러 코드는 정해진 것만: `engine_off` `out_of_range` `missing_arg` `unsafe_while_driving` `not_found` `unknown_tool`.
7. `ontology/vehicle.yaml`의 필드 구조를 바꾸지 않는다. 바꿔야 하면 코드 대신 이유를 설명하고 멈춘다.
8. 새 의존성을 추가하면 `pyproject.toml`에 넣고 이유를 한 줄 남긴다.
9. `.env`, API 키, `data/raw/`의 내용을 출력하거나 커밋하지 않는다.
10. 한국어 주석·docstring 가능. 단 도구 함수의 docstring은 모델에게 전달되는 설명이므로 `vehicle.yaml`의 `description`과 동일하게 유지한다.

## 도구 스키마 작성 원칙 (SLM 기준)

- 이름: `동사_도메인_대상` 소문자 스네이크. `set_hvac_temperature`, `get_vehicle_state`
- description: 언제 쓰는지 한 문장 + 언제 쓰면 안 되는지 한 문장. 3문장 넘기지 않는다
- 파라미터 3개 이하. enum과 min/max로 값 제한. 중첩 객체 금지
- 비슷한 도구 여러 개보다 파라미터로 구분되는 하나
- 기본값이 있으면 명시

## 평가셋 한 건 형식

```json
{"id": "hvac_003", "utt": "뒷자리 너무 덥대", "state": {"Vehicle.LowVoltageSystemState": "ON", "Vehicle.Speed": 40},
 "expected": {"tool": "set_hvac_temperature", "args": {"zone": "rear"}}, "type": "indirect"}
```

`type`: `direct` `indirect` `missing_arg` `multiturn` `unsafe` `no_tool`

## 하지 말 것

- `ontology/generated/` 직접 편집
- `main`에 커밋
- 테스트 없이 채점 로직 변경
- 확인 안 된 VSS 경로, 라이브러리 API, 모델 태그를 사실처럼 쓰기
- 리포트에 모델명·태그·장비·평가셋 버전 빼먹기

## 완료 기준

- 이슈에 적힌 범위만 건드림
- `make lint && make test` 통과
- 온톨로지를 바꿨으면 생성물 갱신됨
- PR 설명에 확인 방법이 있음
