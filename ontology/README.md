# ontology

`vehicle.yaml` 하나가 도구 스키마, 시뮬레이터 초기 상태, 평가셋 검증의 공통 원천이다.

```
vehicle.yaml ──build_schema.py──▶ generated/tools.json          (MCP 서버, 프롬프트, 평가 검증)
                               └▶ generated/initial_state.json  (시뮬레이터)
```

## 기능 한 개의 필드

| 필드 | 필수 | 설명 |
|------|------|------|
| `id` | O | 도구 이름. `동사_도메인_대상`, 소문자 스네이크 |
| `domain` | O | `hvac` `media` `nav` `phone_manual` `settings` `status` |
| `description` | O | 모델에게 보여줄 설명. 언제 쓰는지 + 언제 쓰면 안 되는지. 영어 권장, 3문장 이내 |
| `vss` | O | VSS 경로. `{zone}` 같은 자리표시자는 `instance_map`으로 펼침. get 계열은 `field: path` 맵. 없으면 `null` |
| `ext` | | VSS에 없는 확장 기능이면 `true` |
| `params` | O | 파라미터. `type`(int/float/string/bool/enum), `values`, `min`, `max`, `unit`, `default`, `required` |
| `precondition` | O | `power_on`, `parked`, `speed_below_N`. 빈 리스트 가능 |
| `initial` | | 시뮬레이터 초기값. get 계열은 `field: 값` 맵 |
| `ko` | O | 예시 발화 3개 이상. 직접 명령과 간접 표현 섞기 |

## 규칙

- VSS 경로는 `vss.json`(6.0)에 있는 것만. 확인 방법은 `vss_ref.md`
- 필드 구조를 바꾸려면 이슈 먼저. `build_schema.py`, `tests/test_ontology.py` 같이 수정
- `generated/`는 손으로 편집하지 않는다
- 파라미터는 3개 이하, enum/min/max로 값 제한, 중첩 금지 (SLM 정확도 때문)
