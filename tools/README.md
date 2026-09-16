# tools

MCP Python SDK 2.x 사용. 서버 클래스는 `mcp.server.mcpserver.MCPServer` (1.x 문서의 `FastMCP`는 이름이 바뀐 것).

MCP 도구 서버. `server.py`가 진입점, 도메인별 구현은 `hvac.py`, `media.py`, `nav.py`, `phone.py`, `status.py`.

- 도구 스키마는 `ontology/generated/tools.json`에서 온다. 여기서 새로 정의하지 않는다
- 상태는 `sim.state.VehicleState`만 통해 읽고 쓴다
- 반환은 `sim.state.ok()` / `err()`. 다른 형태 금지
- precondition 검사는 `state.check(...)`로. 직접 if 문으로 안전 규칙 쓰지 않는다

동작 확인: `make server` 로 띄운 뒤 MCP Inspector(`npx @modelcontextprotocol/inspector`)나
`langchain-mcp-adapters`의 `MultiServerMCPClient`로 호출.
