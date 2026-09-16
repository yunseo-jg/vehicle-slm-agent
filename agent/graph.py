"""LangGraph 에이전트. 5주차 구현 대상.

노드 (순서대로)
  intent       발화에서 의도 파악. 도구 불필요(잡담, 질문)면 respond 로
  tool_select  모델이 도구와 인자 JSON 생성
  validate     온톨로지 제약 검사 (코드). 범위·enum·precondition. 인자 빠지면 ask 로 분기
  execute      MCP 서버 호출
  respond      결과를 한국어 한 문장으로

상태(State)에 반드시 들어가는 것
  messages         대화 히스토리 (최근 N턴만)
  vehicle_state    현재 차량 상태 스냅샷. 매 턴 새로 주입. 과거 대화의 값을 현재값으로 쓰지 않는다
  tool_call        선택된 도구와 인자
  tool_result      실행 결과 (ok/err dict)

모델 교체(클라우드 → Ollama)는 build_graph(llm=...) 인자만 바꿔서 되게 만든다.
"""

from __future__ import annotations


def build_graph(llm=None, tools=None):
    raise NotImplementedError("5주차: agent/graph.py 구현")
