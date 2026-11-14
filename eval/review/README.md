# eval/review

검수 주간에 대시보드(`make dashboard`)에서 남긴 기록. 사람별 파일이라 여러 명이 동시에 올려도 충돌하지 않는다.

- `findings_<이름>.jsonl`: 검수 기록. 분류는 `candidate`(평가셋 추가 후보), `expected`(정답 기준 이의), `code`(코드·프롬프트 문제)
- `candidates_<이름>.jsonl`: 평가셋 형식 초안. `expected`와 `type`은 실제 동작에서 채운 값이라 사람이 확인해야 한다

평가셋에 넣을 때는 `draft` 필드를 지우고 `id`를 정해 `eval/data/`로 옮긴 뒤 `make validate-eval`.
