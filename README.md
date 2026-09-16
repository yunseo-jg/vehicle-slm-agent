# vehicle-slm-agent

온디바이스 SLM 기반 Tool-calling 에이전트 (차량 도메인)

네트워크를 끊은 노트북에서 로컬 소형 모델이 사용자의 말을 이해하고 차량 기능을 실행한다.
"에어컨 22도로 맞춰줘" → 모델이 공조 도구를 고르고 → 인자(22)를 채워 → 시뮬레이터 상태를 바꾼다.
클라우드 모델로 먼저 완성한 뒤 로컬 SLM으로 교체하고, 같은 평가셋으로 정확도와 속도를 비교하는 것이 이 프로젝트의 핵심 실험이다.

KUBIG 26-2 AI Agent 개발 1팀 / 2026.09 ~ 2026.11

## 만드는 것

| # | 산출물 | 위치 | 설명 |
|---|--------|------|------|
| 1 | 온톨로지 | `ontology/` | 차량 기능 사전(`vehicle.yaml`). COVESA VSS 6.0 신호 기준. 여기서 도구 스키마와 시뮬레이터 초기 상태를 자동 생성 |
| 2 | MCP 도구 서버 + 시뮬레이터 | `tools/`, `sim/` | 온톨로지에서 생성된 스키마로 도구를 노출. 실제 차량 대신 상태 dict를 조작 |
| 3 | LangGraph 에이전트 | `agent/` | 의도 파악 → 도구 선택 → 인자 검증 → 실행 → 응답. 멀티턴, 안전 가드레일 포함 |
| 4 | 로컬 SLM 서빙 + LoRA | `training/` | Ollama로 소형 모델 서빙, 도구 호출 형식 학습 |
| 5 | 평가셋 + 자동 채점 + 트레이싱 | `eval/`, `reports/` | 직접 만든 평가셋으로 모델별·설정별 수치 비교 |

## 동작 구조

```
사용자 발화
   │
   ▼
[agent/graph.py]  LangGraph
   intent → tool_select → validate → execute → respond
                              │          │
                 온톨로지 제약 검사       │  MCP (stdio)
                 (범위, precondition)    ▼
                                  [tools/server.py]  MCP 서버
                                        │
                                        ▼
                                  [sim/state.py]  차량 상태 dict
                                  (키 = VSS 경로)

평가 루프
   eval/data/*.jsonl ─▶ eval/run_eval.py ─▶ eval/score.py ─▶ reports/YYYYMMDD_*.md
```

- 도구 정의는 코드에 직접 쓰지 않는다. `ontology/vehicle.yaml`이 유일한 원천이고 `build_schema.py`가 나머지를 만든다.
- 모델은 도구를 "고르기만" 한다. 실행과 안전 검사는 코드가 한다.
- 시뮬레이터 상태 키는 VSS 경로를 그대로 쓴다. (`Vehicle.Cabin.HVAC.Station.Row1.Driver.Temperature`)

## 폴더 구조

```
.
├── ontology/          기능 사전. vehicle.yaml + build_schema.py → generated/
├── tools/             MCP 도구 서버 (server.py) 와 도메인별 도구 구현
├── sim/               차량 시뮬레이터 (state.py)
├── agent/             LangGraph 그래프, 프롬프트
├── eval/              평가셋(data/), 실행기(run_eval.py), 채점기(score.py)
├── training/          LoRA 학습 데이터 합성, 학습 노트북
├── reports/           실험 결과. 날짜별 md + 표
├── docs/              아키텍처 문서, 설계 결정 기록(ADR)
├── data/              raw는 커밋 금지. processed만 필요 시 커밋
├── tests/             온톨로지·시뮬레이터·채점기 테스트
├── scripts/           일회성 스크립트
├── AGENTS.md          AI 코딩 도구용 프로젝트 컨텍스트 (Cursor, Codex, Claude Code 등이 읽음)
├── CONTRIBUTING.md    브랜치, 커밋, PR, AI 활용 규칙
└── Makefile           자주 쓰는 명령 모음
```

## 시작하기

요구사항: Python 3.11+, [uv](https://docs.astral.sh/uv/), Git. 로컬 모델 단계(7주차~)부터 Ollama.

```bash
git clone https://github.com/yunseo-jg/vehicle-slm-agent.git
cd vehicle-slm-agent
uv sync                      # 가상환경 + 의존성
cp .env.example .env         # API 키는 여기에. 커밋 금지

make schema                  # ontology/vehicle.yaml → ontology/generated/
make test                    # 온톨로지 검증 + 단위 테스트
make server                  # MCP 서버 stdio로 실행 (동작 확인용)
```

`.env`에 넣을 키는 `.env.example` 참고. 클라우드 모델은 베이스라인 측정용이고, 로컬 전환 후에는 필요 없다.

## 진행 일정

매주 앞 1시간 발제, 뒤 1시간 회의. 중간고사 전까지 클라우드 API 버전 완성, 이후 로컬 SLM 전환.

| 주차 | 날짜 | 발제 | 이번 주 목표 |
|------|------|------|-------------|
| 2 | 9/9 | 에이전트 전체 훑기 | 도메인 확정, 역할 분담, 레포 세팅 |
| 3 | 9/17 | MCP & 도구 스키마 설계 | 기능 목록 확정, 온톨로지 구조 확정 |
| 4 | 9/21 | LangGraph & 대화 흐름 | MCP 서버·시뮬레이터 연결, 베이스라인 동작 |
| 5 | 9/28 | (회식) | 중간 점검, 평가셋 취합 |
| 6 | 10/5 | 에이전트 평가 방법 | 멀티턴·안전 규칙, 평가셋 기준 합의 |
| 7 | 11/2 | 로컬 LLM 서빙 & 양자화 | 채점 도구 완성, 기준 수치 확정 |
| 8 | 11/9 | LoRA & 프롬프트 최적화 | 모델별 비교 |
| 9 | 11/16 | (회식) | 트레이싱·예외 처리, 도메인 교체 데모 |
| 10 | 11/23 | - | 아키텍처 리뷰, 문서·리포트, 발표 준비 |

회의록과 발제 자료는 노션에 있다. 이 레포에는 코드와 실험 결과만 남긴다.

## 협업 규칙 (요약)

- `main`에 직접 푸시하지 않는다. 브랜치 → PR → 리뷰 1명 → squash merge
- 브랜치 이름: `feat/hvac-tools`, `eval/scoring`, `docs/architecture` 처럼 `종류/내용`
- 온톨로지(`vehicle.yaml`)를 바꿨으면 `make schema`를 다시 돌리고 생성물까지 같은 PR에 포함
- 실험 결과는 `reports/`에 날짜 파일로. 모델명·태그, 네트워크 차단 여부, 장비, 평가셋 버전 없으면 리뷰에서 반려
- AI 코딩 도구 사용은 자유. 리뷰는 사람이 하고, 책임은 PR 작성자가 진다. 도구에 `AGENTS.md`를 먼저 읽힌다

자세한 내용은 [CONTRIBUTING.md](CONTRIBUTING.md).

## 참고 자료

- [COVESA VSS](https://covesa.github.io/vehicle_signal_specification/) 차량 신호 표준. 기능 목록의 기준 (6.0)
- [VSS 6.0 릴리스 파일](https://github.com/COVESA/vehicle_signal_specification/releases/tag/v6.0) `vss.json`, `vss.csv`
- [AI Hub 차량 내 대화 및 명령어 음성](https://aihub.or.kr/aihubdata/data/view.do?dataSetSn=112) 한국어 발화 원천. 전사 텍스트만 사용
- [KVRET](https://nlp.stanford.edu/blog/a-new-multi-turn-multi-domain-task-oriented-dialogue-dataset/) 영어 차량 대화 데이터, 구조 참고용
- [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk), [langchain-mcp-adapters](https://github.com/langchain-ai/langchain-mcp-adapters), [LangGraph](https://langchain-ai.github.io/langgraph/)

## 팀

| 이름 | GitHub | 담당 |
|------|--------|------|
| (팀장) | @yunseo-jg | |
| 신진섭 | | |
| 하솔미 | | |
| 홍준기 | | |
| 손윤나 | | |

담당 파트는 3주차 회의에서 확정 후 채운다.
