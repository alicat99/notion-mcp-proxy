# Notion MCP Python bridge

Notion MCP의 클라이언트이면서 로컬 MCP 서버로 동작하는 Python 브릿지다.
시작할 때 원격 도구 목록의 모든 페이지를 읽어 미리 작성된 Python 메서드에 연결하고,
같은 이름·설명·입력 스키마·출력 스키마를 로컬 MCP 클라이언트에 제공한다.
페이지 권한 관리 레이어는 아직 없다. 에이전트·세션 관련 10개 도구는 접근을 거부한다.

```text
client.py
  → tools/call {name, arguments}
server.py                 MCP 요청 파싱 / 함수 선택 / MCP 응답
  → functions[name](**arguments)
tool_functions.py         42개 명시적 Python 메서드 / JSON Schema 검사 / 향후 권한 검사 위치
  → upstream.call_tool(name, arguments)
upstream.py               SDK 연결 / 공통 tools/call 조립 / 전송 / 응답 수신
  → https://mcp.notion.com/mcp
```

도구별로 달라지는 것은 이름과 인자 JSON이다. 전송 형식은 공통이므로 `upstream.py`에 분리했다.
`tool_functions.py`의 `NotionTools` 클래스에 42개 도구가 각각 `async def`로 존재한다.
`fetch`, `search`, `create_pages`, `update_page`처럼 이름·인자·설명을 코드에서 직접 확인하고 수정한다.
필수 인자는 기본값 없이, 선택 인자는 `UNSET`으로 선언한다. 선택 인자를 생략하면 전송하지 않고,
명시적으로 전달한 `None`, `False`, 빈 목록은 보존한다. 단, 실제 값은 서버 스키마 검증을 통과해야 한다.
중첩 인자는 원래 JSON 구조를 유지한다. 예를 들어 `query_data_sources(data=...)`의 모드별 필드는 data 내부에 넣는다.

파일 하단의 `TOOL_METHODS`가 MCP 이름과 Python 메서드를 명시적으로 연결한다.
예: `notion-fetch` → `fetch`, `notion-create-pages` → `create_pages`.
새 함수를 런타임에 생성하거나 인자 제한 없는 함수를 대신 노출하지 않는다.

`notion_tools.json`에는 2026-09-08 실제 Notion MCP의 tools/list로 받은 42개 도구의 설명과 전체 스키마를 저장했다.
도구 구현 시 참고하는 목록이며 런타임 권한·실행 가능 여부를 보장하지 않는다. 서버는 시작할 때 실시간 스키마를 사용한다.
이번 조회에서는 원격 도구 메타데이터만 저장했으며 OAuth 자격 증명은 포함하지 않았다.

## 설치

Python 3.13 이상과 uv가 필요하다. 프로젝트 루트에서 실행한다.

```powershell
Set-Location 'D:\AI Projects\notion-proxy'
uv sync --frozen
```

`vendor/python-sdk`는 공식 SDK를 일반 파일로 포함한 디렉토리다. 별도 클론·서브모듈 초기화는 필요 없다.

## 서버 실행: 터미널 A

```powershell
uv run --frozen python -X utf8 server.py
```

서버가 Notion OAuth 인증을 진행하고 도구를 조회한다. 저장된 인증이 유효하면 재사용한다.
처음 인증하거나 재인증이 필요하면 다음과 같이 진행한다.

1. 서버가 연 브라우저에서 Notion 로그인·연결 승인을 한다.
2. `http://127.0.0.1:8765/callback?...`으로 이동한 주소 전체를 복사한다.
3. **터미널 A의 `Callback URL:`**에 쿼리를 포함해 붙여넣는다.
4. `Loaded ... tools. Bridge: http://127.0.0.1:6378/mcp`와 Uvicorn 시작 메시지를 기다린다.

콜백 HTTP 서버는 실행하지 않는 수동 입력 방식이므로 브라우저의 연결 실패 화면은 정상이다.
콜백 URL은 일회용 인증 코드를 포함하므로 공유하거나 이전 URL을 재사용하지 않는다.
종료는 Ctrl+C. 로컬 포트를 바꾸려면 `--port 6379`을 추가한다.

OAuth·keyring은 서버 프로세스에만 있다. 최소 클라이언트에서는 로그인하지 않는다.
기존 `client.py --oauth` 방식은 제거했다.

## 최소 클라이언트: 터미널 B

전체 도구 목록과 입력 스키마:

```powershell
uv run --frozen python -X utf8 client.py
```

연결 정보 읽기:

```powershell
uv run --frozen python -X utf8 client.py --tool notion-fetch --args-file examples/notion-self.json
```

다른 포트의 브릿지에 연결:

```powershell
uv run --frozen python -X utf8 client.py --url http://127.0.0.1:6379/mcp
```

`-X utf8`은 Windows 한국어 입출력을 위한 옵션이다.

## 다른 프로젝트의 Codex에서 연결

다른 프로젝트 루트의 `.codex/config.toml`에 다음 설정을 추가한다.
복사 가능한 파일은 `examples/codex-config.toml`이다. 기존 설정이 있으면 해당 섹션만 병합한다.

```toml
[mcp_servers.notion_proxy]
url = "http://127.0.0.1:6378/mcp"
tool_timeout_sec = 120
```

먼저 이 프로젝트에서 `uv run --frozen python -X utf8 server.py`를 실행하고 OAuth 및 도구 로딩을 완료한다.
그 다음 대상 프로젝트의 Codex를 다시 열어 연결한다. 이 URL 설정은 이미 실행 중인 서버에 연결하며,
서버 프로세스를 자동으로 시작하지 않는다. 서버 터미널을 계속 실행해 두어야 한다.
Notion OAuth는 브릿지가 담당하므로 이 설정에 Notion 토큰이나 OAuth 설정을 넣지 않는다.

프로젝트별 `.codex/config.toml`은 Codex에서 신뢰한 프로젝트에 적용된다.
Codex와 브릿지는 같은 컴퓨터에서 실행해야 한다. 원격 환경의 `127.0.0.1`은 이 Windows 컴퓨터를 가리키지 않는다.
여러 프로젝트가 같은 서버 URL을 사용할 수 있으며, 모두 동일한 Notion 연결과 현재 권한을 공유한다.

설정 형식 참고: [OpenAI 공식 MCP 연결 문서](https://developers.openai.com/codex/mcp).

## 원하는 도구 호출

1. 목록의 `tools[].name`, `description`, `inputSchema`를 확인한다.
2. 입력 스키마에 맞는 JSON 객체를 파일로 작성한다.
3. 그 이름과 파일을 지정한다. 인자가 없으면 `--args-file`을 생략한다.

```powershell
uv run --frozen python -X utf8 client.py --tool notion-fetch --args-file examples/notion-page.json
```

`examples/notion-page.json`의 페이지 ID를 실제 값으로 수정한 뒤 실행한다.
도구 이름은 서버가 실제로 반환한 값을 사용한다. 쓰기 도구도 같은 방법으로 호출하며 실제 Notion에 반영된다.
입력은 UTF-8/BOM JSON을 지원한다. 중첩 객체, 배열, false, null을 그대로 전달한다.

여러 도구를 같은 연결에서 연속 호출하려면 `client.py`의 `# Additional calls` 부분을 수정한다.

```python
result = await client.call_tool("notion-fetch", {"id": "self"})
print(result.model_dump_json(indent=2, by_alias=True))

result = await client.call_tool("실제 도구 이름", {"실제 인자": "값"})
print(result.model_dump_json(indent=2, by_alias=True))
```

MCP 결과는 `content`, `structuredContent`, `isError` 등을 포함한다.
텍스트·이미지 등 콘텐츠 블록을 임의로 문자열화하거나 JSON으로 재해석하지 않고 SDK 결과를 반환한다.
`isError: true`인 도구 결과는 그대로 출력되며 CLI의 종료 코드와는 별개다.
알 수 없는 도구·입력 스키마 위반은 MCP `INVALID_PARAMS`로 거부한다.
네트워크 오류나 상위 MCP 오류를 숨기거나 쓰기 요청을 임의로 반복 실행하지 않는다.

## MCP 없이 Python 래퍼 직접 호출

```python
import asyncio
from tool_functions import NotionTools
from upstream import connect_upstream

async def main():
    async with connect_upstream("https://mcp.notion.com/mcp") as upstream:
        tools = NotionTools(upstream, await upstream.list_tools())
        result = await tools.fetch(id="self")
        print(result.model_dump_json(indent=2, by_alias=True))

asyncio.run(main())
```

`tool_functions.py`는 MCP 서버나 HTTP 프레임워크를 import하지 않는다.
페이지 조회 정책은 `fetch()`에, 페이지 수정 정책은 `update_page()`에 추가할 수 있다.
공통 정책은 `_call()`의 스키마 검증과 `upstream.call_tool()` 사이에 추가한다.
MCP 호출과 직접 Python 호출 모두 같은 메서드를 거친다. 아직 권한 검사는 구현하지 않았다.

새 도구 추가 방법:

1. 실제 tools/list의 이름·설명·inputSchema를 확인한다.
2. 클래스에 명시적인 async 메서드를 추가하고 필수·선택 인자를 선언한다.
3. 메서드에서 인자를 딕셔너리로 구성해 `_call("원래 MCP 이름", arguments)`에 전달한다.
4. `TOOL_METHODS`에 MCP 이름과 메서드 이름을 등록한다.
5. `notion_tools.json` 참고 스키마와 테스트를 업데이트하고 서버를 재시작한다.

서버에 새 도구가 생겼는데 명시적 메서드가 없으면 시작을 중단하고 도구 이름을 알려준다.
실시간 스키마의 최상위 인자 이름과 메서드 시그니처가 달라진 경우에도 수정할 도구를 알려준다.
이는 중간 브릿지와 코드상의 도구 목록이 서로 달라진 채 동작하는 것을 방지한다.

## 에이전트·세션 도구 차단

`tool_functions.py`의 `BLOCKED_TOOLS`에 다음 10개를 명시했다.

- `notion-search-agents`
- `notion-search-sessions`
- `notion-query-sessions`
- `notion-spawn-session`
- `notion-get-session-status`
- `notion-wait-session`
- `notion-stop-session`
- `notion-send-message-to-session`
- `notion-list-session-events`
- `notion-read-session-event`

이 도구들은 tools/list에서 제외된다. 이름을 알고 tools/call로 호출해도 MCP 오류 `-32003`으로 거부한다.
Python 메서드는 기능 목록으로 남기되 직접 호출하면 `PermissionError`를 발생시키며 상위 Notion으로 전달하지 않는다.
원본 42개 도구가 그대로 노출되는 환경에서는 브릿지가 32개를 제공한다.
변경 적용에는 서버 재시작과 클라이언트의 도구 목록 갱신이 필요하다.
Skill 페이지 지정·검색과 회의록 조회는 에이전트 세션 실행 기능이 아니므로 이번 차단에는 포함하지 않는다.

## 연결과 지원 범위

- 서버 시작 시 발견한 도구 중 에이전트·세션 도구를 제외하고 명시적 메서드에 연결해 노출한다. 현재 연결에서 노출되지 않은 메서드는 호출할 수 없다. 도구 목록 변경은 재시작 시 반영하고, 새로운 도구·인자는 위 절차로 코드를 수정한다.
- 실제 실행 가능 여부는 Notion 사용자 권한·요금제에 따른다.
- 상위 연결 하나를 공유하며 요청을 직렬화한다. 토큰 동시 갱신을 피하기 위한 단일 프로세스 구성이다.
- 동일 OAuth 저장소를 쓰는 서버·직접 호출 스크립트를 동시에 실행하지 않는다. 프로세스 간 잠금은 없다.
- 로컬 서버는 `127.0.0.1`에만 바인딩한다. 하위 클라이언트 인증은 없으므로 같은 컴퓨터의 프로세스가 도구를 호출할 수 있다.
- tools/list와 tools/call을 중계한다. resources/prompts, sampling/elicitation 콜백, 진행 알림까지 중계하는 완전한 MCP 프록시는 아니다.
- 도구 반환값 안의 Notion 비동기 작업 ID는 그대로 반환한다. 완료 확인 도구는 호출자가 추가 호출한다.
- 파일 업로드 도구가 별도 HTTP 업로드 URL을 반환하면 파일 전송은 호출자가 수행한다.
- 상위 서버 연결이 끊기면 서버를 재시작한다. 쓰기 중 연결이 끊겼다면 실제 반영 여부부터 확인한다.

## OAuth 저장과 초기화

`oauth.py`는 공식 SDK의 `OAuthClientProvider`를 재사용한다.
`token_endpoint_auth_method="none"`과 PKCE를 사용하며, 토큰과 등록 정보를 Windows Credential Manager에 저장한다.
기존 자격 증명을 재사용하기 위해 keyring 서비스 이름은 유지했다.

`invalid_grant` 등으로 재인증이 실패하면 서버를 종료하고 아래에서 존재하는 항목을 삭제한 뒤 다시 실행한다.

```powershell
uv run --frozen python -c "import keyring; keyring.delete_password('notion-proxy-playground:https://mcp.notion.com/mcp', 'tokens')"
```

이전 Basic 인증 등록 때문에 `Client must not use multiple authentication methods`가 발생하거나
등록 정보 자체를 초기화해야 할 때는 `client_info`도 삭제한다.

```powershell
uv run --frozen python -c "import keyring; keyring.delete_password('notion-proxy-playground:https://mcp.notion.com/mcp', 'client_info')"
```

저장된 항목이 없으면 삭제 명령은 오류를 낸다. 로컬 삭제는 Notion 측 연결 취소와는 별개다.

## 검증

```powershell
uv run --frozen python -X utf8 -m unittest discover -s tests -v
```

테스트는 실제 HTTP 포트에 가짜 상위 MCP와 브릿지를 실행한다. 도구 목록 페이지네이션,
스키마 보존, 중첩 인자, 한글·이미지·구조화 결과, 오류 결과, 잘못된 요청 차단,
Python 래퍼 직접 호출과 최소 CLI 프로세스 실행을 검증한다. 42개 스키마와 명시적 메서드의 일치,
선택 인자의 생략/null/false 구분, 새 도구·변경된 인자 감지도 검증한다. Notion 계정이나 OAuth 승인은 필요 없다.
실제 Notion과의 OAuth·도구 호출은 별도 로그인 후 확인해야 한다.

다른 테스트용 MCP를 중계할 때만 다음 옵션을 사용한다.

```powershell
uv run --frozen python -X utf8 server.py --upstream http://127.0.0.1:9000/mcp --no-oauth
```

## SDK 출처

- 공식 저장소: https://github.com/modelcontextprotocol/python-sdk
- 원본 커밋: `9972c21aa42054fb1450c5fc614761ed11847ec6` (2.2.0)
- SDK 실행 코드는 원본 유지. 일반 파일 통합을 위해 두 패키지의 pyproject.toml에서 Git 기반 버전 생성을 2.2.0으로 고정했다.
- MIT LICENSE를 vendor에 유지한다. vendor 수정도 루트 Git 저장소에서 관리한다.
- SDK는 로컬 editable 의존성이므로 vendor 코드 수정이 실행에 반영된다.
