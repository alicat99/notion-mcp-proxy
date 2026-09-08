# Notion MCP Python 실험 환경

공식 MCP Python SDK를 일반 파일로 포함하고, SDK 기반 로컬 테스트 서버와 범용 HTTP 클라이언트를 구성했다.
페이지 권한 검사나 도구 제한은 없다. Notion 도구를 호출하면 로그인한 사용자의 실제 워크스페이스에 적용된다.

## 파일 구성

- `vendor/python-sdk/`: 공식 SDK 소스 사본. 내부 .git이나 서브모듈 없이 루트 저장소에서 관리한다. 로컬 editable 의존성으로 사용한다.
- `server.py`: `echo`, `add`를 제공하는 로컬 MCP 서버.
- `client.py`: 도구 전체 목록·스키마 출력 또는 지정한 도구 호출.
- `oauth.py`: SDK OAuth provider, 수동 콜백 입력, Windows Credential Manager 저장.
- `examples/`: 도구 인자 JSON 예제.

클론 주소: https://github.com/modelcontextprotocol/python-sdk

검증한 커밋: `9972c21aa42054fb1450c5fc614761ed11847ec6` (SDK 2.2.0).
SDK 실행 코드는 원본 그대로다. 일반 파일 통합을 위해 SDK와 mcp-types의 pyproject.toml에서
Git 기반 동적 버전·의존성 생성을 정적 버전 2.2.0으로 변경했다. MIT LICENSE는 유지한다.
이제 vendor 내부 수정도 루트 저장소의 일반 diff와 commit에 포함된다.
이 예제는 SDK v2용이며 v1 예제의 import/API와 섞지 않는다.

## 1. 환경 준비

Python 3.13 이상과 uv가 필요하다. 현재 작업 환경에는 `.venv`와 의존성 설치가 완료되어 있다.
PowerShell에서 프로젝트 루트로 이동한다.

```powershell
Set-Location 'D:\AI Projects\notion-proxy'
uv sync --frozen
```

다른 컴퓨터에서는 이 프로젝트를 일반 git clone한 뒤 uv sync --frozen을 실행한다.
SDK가 함께 포함되므로 추가 클론이나 서브모듈 명령은 필요 없다.

## 2. 로컬 MCP 서버 실행

터미널 A:

```powershell
uv run --frozen python -X utf8 server.py
```

주소는 `http://127.0.0.1:8000/mcp`이다. 종료는 Ctrl+C.
이 서버는 프로토콜 테스트용이며 Notion을 대리 호출하는 프록시는 아니다.

터미널 B에서 전체 도구와 입력 JSON Schema를 확인한다.

```powershell
uv run --frozen python -X utf8 client.py
```

도구 호출:

```powershell
uv run --frozen python -X utf8 client.py --tool echo --args-file examples/echo.json
uv run --frozen python -X utf8 client.py --tool add --args-file examples/add.json
```

각각 한국어 메시지와 `42.0`이 `content`에 출력된다.
`-X utf8`은 Windows의 한글 콘솔 출력 인코딩을 맞춘다.
서버에 도구를 추가하려면 `@server.tool()` 함수를 작성하고 서버를 재시작한다.

## 3. Notion MCP에 연결

로컬 테스트 서버는 필요 없다. 동일한 클라이언트가 Notion 원격 MCP로 직접 연결한다.

```powershell
uv run --frozen python -X utf8 client.py --url https://mcp.notion.com/mcp --oauth
```

1. 처음 실행하면 기본 브라우저에서 Notion 로그인이 열린다.
2. 사용할 워크스페이스를 선택하고 연결을 승인한다.
3. 브라우저가 `http://127.0.0.1:8765/callback?...`으로 이동한다.
4. **연결 실패 화면이 정상이다.** 최소 예제라 해당 포트에 콜백 서버를 실행하지 않는다.
5. 브라우저 주소 표시줄의 전체 URL을 터미널 `Callback URL:`에 붙여넣고 Enter를 누른다.
6. SDK가 state/issuer 검증과 코드 교환을 수행하고 도구 목록을 출력한다.

이 방식은 공식 SDK의 수동 콜백 예제를 따른다. 콜백 URL에는 일회성 인증 코드가 있으므로 공유하지 않는다.
코드 길이를 줄이기 위해 자동 콜백 웹서버는 넣지 않았다.

읽기 전용 연결정보 조회 예제:

```powershell
uv run --frozen python -X utf8 client.py --url https://mcp.notion.com/mcp --oauth --tool notion-fetch --args-file examples/notion-self.json
```

실제 도구 이름은 앞서 출력한 `tools[].name`을 사용한다. 서버가 다른 이름으로 노출하면 `--tool`을 맞춘다.

## 4. 모든 도구를 직접 호출하는 방법

도구 이름을 하드코딩한 허용 목록은 없다. `tools/list`는 `nextCursor`가 없을 때까지 조회한다.

1. 목록에서 `name`, `description`, `inputSchema`를 확인한다.
2. 스키마에 맞춘 JSON 객체를 파일로 작성한다. UTF-8과 UTF-8 BOM 모두 지원한다.
3. `--tool 도구이름 --args-file 파일경로`로 호출한다. 인자가 없으면 `--args-file`을 생략한다.

예를 들어 페이지 읽기 인자 파일은 다음과 같다.

```json
{"id": "실제 페이지 URL 또는 ID"}
```

Python에서 여러 도구를 연속 호출하려면 `client.py`의 `# Additional calls` 부분을 수정한다.
반드시 `async with Client(...)` 블록 안에 둔다. 앞선 응답에서 ID를 꺼내 다음 호출에 전달할 수도 있다.

```python
result = await client.call_tool("notion-fetch", {"id": "self"})
print(result.model_dump_json(indent=2, by_alias=True))

# 실제 tools/list 스키마에 맞춰 이름과 인자를 변경한다.
result = await client.call_tool("원하는 도구 이름", {"인자": "값"})
print(result.model_dump_json(indent=2, by_alias=True))
```

결과의 `content`는 텍스트·이미지 등 MCP 콘텐츠 블록이다. `structuredContent`가 있으면 구조화 결과도 확인할 수 있다.
텍스트가 항상 JSON인 것은 아니므로 모든 text에 무조건 `json.loads()`를 적용하지 않는다.
서버가 반환하는 `isError`와 SDK 예외를 확인한다. 실패를 숨기는 예외 처리는 추가하지 않았다.
비동기 작업 ID를 반환하는 Notion 도구는 그 ID를 상태 조회 도구에 넘겨 완료를 확인한다.
SDK가 Notion 고유의 비동기 작업 완료까지 자동으로 기다리는 것은 아니다.

도구 이름 제한은 없지만 서버의 요금제·사용자 권한은 그대로 적용된다.
sampling/elicitation 등 추가 상호작용을 요구하는 서버는 해당 SDK 콜백을 별도로 구성해야 한다.

## 5. OAuth 저장과 초기화

SDK가 discovery, 등록, PKCE, 인증 코드 교환과 토큰 갱신을 처리한다.
Notion 문서에 맞춰 `token_endpoint_auth_method="none"`을 명시한 public client와 PKCE를 사용한다.
이를 생략하면 등록 서버가 `client_secret_basic`을 선택할 수 있다. 현재 SDK의 Basic 인증 헤더와
본문 `client_id` 조합을 Notion이 중복 인증으로 거부하면 `Client must not use multiple authentication methods`가 발생한다.
이전 설정으로 이미 등록했다면 아래 초기화 명령으로 기존 `tokens`(있는 경우)와 `client_info`를 제거하고 새로 승인한다.
설정 변경만으로는 저장된 등록 정보가 바뀌지 않는다. 기존 콜백 URL도 재사용하지 않는다.
`oauth.py`는 `tokens`와 `client_info`를 keyring에 저장한다. Windows에서는 Credential Manager를 사용한다.
서비스 이름은 `notion-proxy-playground:https://mcp.notion.com/mcp`이다.
토큰을 소스 코드나 JSON 파일에 저장하지 않는다.

이 최소 예제는 **한 번에 하나의 OAuth 클라이언트 프로세스**를 실행하는 전제다.
동일한 연결을 여러 프로세스로 동시에 갱신하는 잠금은 구현하지 않았다.
토큰 갱신이 불가능하면 재인증이 필요하다. SDK 예외가 발생하면 아래처럼 토큰만 초기화하고 다시 실행한다.

```powershell
uv run --frozen python -c "import keyring; keyring.delete_password('notion-proxy-playground:https://mcp.notion.com/mcp', 'tokens')"
```

등록 정보 자체도 초기화해야 하는 경우에만 다음을 추가로 실행한다.

```powershell
uv run --frozen python -c "import keyring; keyring.delete_password('notion-proxy-playground:https://mcp.notion.com/mcp', 'client_info')"
```

저장된 항목이 없으면 삭제 명령은 오류를 낸다. 로컬 자격 증명 삭제는 Notion 측 연결 취소와는 별개다.

## 검증 범위

- 실제 HTTP 서버를 실행하고 도구 목록과 입력 스키마 수신 확인.
- `echo`와 `add` 요청·응답 확인.
- OAuth provider 생성과 Windows keyring backend 확인.
- Notion OAuth 승인과 실제 워크스페이스 호출은 사용자 로그인 후 검증해야 한다.

참고: [공식 OAuth 예제](https://github.com/modelcontextprotocol/python-sdk/blob/main/docs_src/oauth_clients/tutorial001.py),
[Notion MCP 클라이언트 문서](https://developers.notion.com/guides/mcp/build-mcp-client).
