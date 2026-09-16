# CONTRIBUTING

5명이 같은 코드를 만지고, 각자 AI 도구를 쓰면서도 결과물이 하나로 합쳐지게 하기 위한 규칙이다.
규칙이 불편하면 바꾸자고 이슈를 올린다. 몰래 안 지키는 것보다 낫다.

## 1. 브랜치

- `main`: 항상 동작하는 상태. 직접 푸시 금지
- 작업 브랜치: `종류/짧은-설명`

| 종류 | 용도 | 예 |
|------|------|----|
| `feat/` | 기능 추가 | `feat/hvac-tools`, `feat/validate-node` |
| `fix/` | 버그 수정 | `fix/window-zone-enum` |
| `eval/` | 평가셋, 채점기, 실험 | `eval/hvac-dataset`, `eval/qwen3-4b-run` |
| `docs/` | 문서만 | `docs/architecture` |
| `exp/` | 실험용, 머지 안 할 수도 있음 | `exp/tool-rag` |

- 브랜치 하나 = 목적 하나. 공조 도구 만들다가 채점기까지 고치지 않는다
- 오래 끌지 않는다. 3일 넘어가면 일단 PR 열고 Draft로 둔다

## 2. 커밋

- 형식: `타입(범위): 내용`
  - `feat(hvac): set_hvac_temperature 도구 추가`
  - `fix(sim): 창문 위치 범위 검사 누락`
  - `eval(data): 공조 평가 문장 50건 추가`
  - `docs(ontology): precondition 종류 설명`
- 타입: `feat` `fix` `eval` `docs` `refactor` `test` `chore`
- 범위: 폴더명 또는 도메인명 (`hvac` `media` `nav` `phone` `status` `sim` `agent` `eval` `ontology`)
- 내용은 한국어로 써도 된다. 무엇을 왜 바꿨는지가 보이면 됨
- 생성물(`ontology/generated/`)은 원천 변경과 같은 커밋에 넣는다

## 3. 이슈

- 주차별 할 일은 전부 이슈로 만든다. 회의에서 정한 것 → 그날 밤 안에 이슈 등록
- 제목: `[도메인] 할 일` (`[hvac] 온도·풍량 도구 스키마 작성`)
- 라벨: `domain:hvac` `domain:media` `domain:nav` `domain:phone` `domain:status` / `area:agent` `area:eval` `area:sim` `area:training` / `week:3`
- 담당자 지정 필수. 담당자 없는 이슈는 아무도 안 한다

## 4. PR

- 템플릿(`.github/PULL_REQUEST_TEMPLATE.md`) 채운다. 특히 "확인 방법"
- 리뷰어 1명 이상. 자기 도메인 아닌 사람이 봐도 이해되게 설명 쓴다
- CI 통과 필수 (`ruff`, `pytest`, 온톨로지 검증)
- 승인 후 본인이 squash merge. 머지 후 브랜치 삭제
- PR 크기: diff 500줄 넘으면 쪼갠다. 생성 파일은 예외
- 리뷰는 24시간 안에. 못 보면 한마디 남긴다

## 5. 코드

- Python 3.11+, `uv`로 의존성 관리. 새 패키지 추가 시 PR 설명에 이유 한 줄
- 포맷·린트: `ruff` (설정은 `pyproject.toml`). `make lint`로 확인
- 타입 힌트 필수. 도구 함수의 타입 힌트와 docstring이 그대로 도구 스키마가 되므로 특히 정확하게
- 도구 함수 반환 형식 고정

```python
{"status": "ok" | "error", "code": "engine_off" | "out_of_range" | ..., "state_after": {...}}
```

- VSS 경로를 코드에 하드코딩하지 않는다. `ontology/vehicle.yaml`에서 읽는다
- 에러 코드 목록: `engine_off` `out_of_range` `missing_arg` `unsafe_while_driving` `not_found` `unknown_tool`. 추가하려면 `docs/decisions.md`에 기록

## 6. 온톨로지 변경

`ontology/vehicle.yaml`은 도구 스키마, 시뮬레이터 초기 상태, 평가셋 검증의 공통 원천이다.

- 기능 추가·수정 → `make schema` → 생성물 확인 → 테스트 → 같은 PR
- 필드 추가(구조 변경)는 반드시 이슈로 먼저 논의. `build_schema.py`와 `tests/test_ontology.py`를 같이 고친다
- VSS 경로는 `vss.json`(6.0)에서 실제로 존재하는지 확인하고 넣는다. AI가 알려준 경로를 그대로 믿지 않는다
- VSS에 없는 기능은 `vss: null`, `ext: true`

## 7. 데이터

- `data/raw/`는 커밋하지 않는다 (`.gitignore` 처리됨). AI Hub 원본은 각자 받는다
- AI Hub 데이터는 재배포 조건이 있으므로 원본 문장을 그대로 레포에 올리지 않는다. 가공한 평가셋만 올린다
- 평가셋 형식은 `eval/README.md`. 한 줄에 한 건(jsonl), `id`는 `도메인_번호`
- 평가셋에 넣기 전 `make validate-eval`로 온톨로지와 대조한다 (없는 도구, 범위 밖 값 걸러냄)

## 8. 실험과 리포트

- 결과는 `reports/YYYYMMDD_<주제>.md`. 템플릿은 `reports/TEMPLATE.md`
- 필수 항목: 모델명과 태그(양자화 포함), 네트워크 차단 여부, 장비(CPU/RAM/GPU), 평가셋 버전(커밋 해시 또는 파일명), 측정 방식, 결과 표
- 하나라도 빠지면 재현이 안 되므로 리뷰에서 돌려보낸다
- 프롬프트를 바꿨으면 전후를 같은 평가셋으로 돌린 결과를 함께 올린다
- 그래프·표 원본 데이터(csv)는 `reports/data/`에

## 9. AI 도구 활용 규칙

Cursor, Claude Code, Codex, Copilot 등 뭘 쓰든 상관없다. 단:

- 작업 시작 전에 도구에게 `AGENTS.md`를 읽힌다. 프로젝트 규칙과 폴더 역할이 들어 있어서 엉뚱한 곳에 파일을 만들거나 형식을 깨는 일이 줄어든다
- AI가 만든 코드도 PR 작성자가 읽고 이해한 뒤 올린다. "AI가 짰는데 저도 잘 모르겠어요"는 리뷰 반려 사유
- AI가 대량으로 만든 것(평가 문장, 도구 설명 등)은 PR 설명에 "합성" 표시하고, 생성 스크립트나 프롬프트를 `scripts/` 또는 `training/`에 남긴다. 재현 안 되는 합성 데이터는 안 받는다
- VSS 경로, 라이브러리 API, 모델 이름은 AI 답변을 그대로 믿지 말고 공식 문서나 실제 파일로 확인한다
- `.env`, API 키, 원본 데이터를 AI 도구 컨텍스트에 넣지 않는다
- 리뷰에 AI를 써도 되지만 최종 승인은 사람이 누른다

## 10. 소통

- 결정은 노션 회의록에, 코드 관련 논의는 이슈·PR에. 슬랙에서 결정된 건 이슈에 한 줄 남긴다
- 막히면 30분 넘기지 말고 슬랙에 올린다
- 다른 사람 브랜치를 건드려야 하면 먼저 말한다
