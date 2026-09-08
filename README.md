# Notion MCP Proxy

Notion MCP Proxy는 **공식 Notion MCP 서버와 클라이언트 사이에서 페이지 계층 기반 접근 제어를 수행하는 MCP 프록시 서버**다. 지정한 단일 루트 페이지와 그 하위 트리를 접근 허용 범위로 설정하고, 수신한 도구 호출을 Python 함수에 매핑하여 권한 정책을 검증한 후 업스트림 Notion MCP 서버로 전달한다.

```text
Codex 등 MCP 클라이언트 → Notion MCP Proxy → 공식 Notion MCP
                         권한 검사          OAuth 연결
```

## 서버 실행

### 설치

Python 3.13 이상과 [uv](https://docs.astral.sh/uv/)가 필요하다. 프로젝트 루트에서 실행한다.

```powershell
git clone https://github.com/alicat99/notion-mcp-proxy.git
cd notion-mcp-proxy
uv sync --frozen
```

[공식 MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)는 `vendor/python-sdk/`에 포함되어 있어 별도 클론은 필요 없다.

### 허용 루트 설정과 전자서명

[config/permissions.toml](config/permissions.toml)에 절대 제목 경로와 루트 페이지 ID를 지정한다.

```toml
[fetch]
# Notion 페이지 제목을 최상위 페이지부터 허용 루트까지 순서대로 나열한 경로다.
# ["홈", "test"]는 최상위 "홈" 페이지 아래의 "test" 페이지를 허용 루트로 지정한다.
# "test" 자체와 그 하위 페이지만 허용하며, "홈"이나 "test"의 형제 페이지는 허용하지 않는다.
# 파일 시스템 경로나 독립적으로 허용할 페이지 목록이 아니다. 빈 배열은 객체 접근을 거부한다.
root_path = ["홈", "test"]

# root_path의 마지막 페이지(이 예에서는 "test")의 UUID다. 검색마다 경로와 대조한다.
root_id = "허용 루트 페이지의 실제 UUID"
```

위 ID는 설명용 자리표시자다. 저장소의 설정은 기존 테스트 환경용이므로 자신의 Notion 환경에 맞는 설정을 사용한다. 루트 자체와 하위 페이지를 허용하며 상위 페이지는 허용하지 않는다. 검색 시에는 ID가 해당 경로의 루트인지도 확인한다.

설정 전체는 Ed25519로 서명되어 있다. 설정을 변경하면 개인키가 있는 관리 컴퓨터에서 다시 서명한다.

```powershell
uv run --frozen python -m notion_proxy.sign_permissions
```

변경된 `config/permissions.toml`과 `config/permissions.sig`를 함께 배포한다. 주석·공백·줄바꿈 변경도 재서명이 필요하다.

| 파일 | 용도 |
|---|---|
| `config/permissions-public.pem` | 서버의 서명 검증 공개키. Git에 포함 |
| `config/permissions.sig` | 승인한 설정의 서명. Git에 포함 |
| `.private/permissions-private.pem` | 설정 변경 시 사용하는 개인키. Git 제외 |

`sign_permissions --init`은 키가 없는 새 환경에서만 사용하며 기존 키를 덮어쓰지 않는다. 기존 공개키가 포함된 복제본에서는 관리자가 서명한 설정을 배포받는다.

### 실행과 Notion 인증

```powershell
uv run --frozen python -X utf8 -m notion_proxy.server
```

서버는 먼저 설정 서명을 검증하고 파일 누락·검증 실패 시 시작을 중단한다. 이후 Notion 인증이 필요하면 다음 절차를 진행한다.

1. 서버가 연 브라우저에서 Notion 연결을 승인한다.
2. 이동한 `http://127.0.0.1:8765/callback?...` 주소 전체를 쿼리까지 복사한다.
3. 서버 터미널의 `Callback URL:`에 붙여넣는다.
4. `Loaded ... tools. Bridge: http://127.0.0.1:6378/mcp` 메시지를 확인한다.

콜백 웹 서버를 실행하지 않는 방식이므로 브라우저의 연결 실패 화면은 정상이다. 인증 정보는 OS keyring에 저장하며 Windows에서는 Credential Manager를 사용한다. 저장소를 복사해도 인증 정보는 따라가지 않는다.

종료는 Ctrl+C, 포트 변경은 `--port 6379`를 사용한다. 설정·코드 변경 후에는 서버를 재시작한다. `-X utf8`은 Windows 한국어 입출력을 위한 옵션이다.

## MCP 서버 연결 설정

Streamable HTTP를 지원하는 MCP 클라이언트에서 다음 주소로 연결한다.

```text
http://127.0.0.1:6378/mcp
```

Notion OAuth는 프록시가 담당하므로 클라이언트에 Notion 토큰을 넣지 않는다. 서버는 같은 컴퓨터의 루프백 주소에 바인딩하며 클라이언트별 인증·권한 분리는 제공하지 않는다.

### Codex

연결할 프로젝트의 `.codex/config.toml`에 다음 설정을 추가한다. 프로젝트별 설정은 신뢰한 프로젝트에서 사용하며 사용자 공통 설정은 `~/.codex/config.toml`에 둘 수 있다.

```toml
[mcp_servers.notion_proxy]
url = "http://127.0.0.1:6378/mcp"
tool_timeout_sec = 120
```

먼저 프록시 서버를 실행하고 Notion 인증을 완료한 뒤 Codex를 열거나 다시 시작한다. 이 URL 설정은 실행 중인 서버에 연결하며 서버를 자동 실행하지 않는다. 포트를 바꿨다면 URL도 맞춘다. 원격 환경의 `127.0.0.1`은 프록시가 실행되는 컴퓨터를 가리키지 않는다.

설정 예제: [examples/codex-config.toml](examples/codex-config.toml). 설정 형식: [OpenAI 공식 MCP 문서](https://learn.chatgpt.com/docs/extend/mcp?surface=cli).

참고용 Python 클라이언트는 [examples/client.py](examples/client.py)에 있다. 사용법은 코드 주석에 정리했으며 클라이언트 구현은 서버 프로젝트의 범위에 포함하지 않는다.

## 지원 도구와 권한 제약

원본 스냅샷 42개 중 **12개를 노출**한다. 10개는 권한 검사 대상이며 업로드 생성 2개는 항상 허용한다. 실제 목록은 시작 시 공식 Notion MCP가 제공한 도구를 기준으로 한다. 새 도구나 변경된 최상위 인자는 명시적인 래퍼를 수정하기 전까지 시작 단계에서 거부한다.

| 도구 | 기능 및 제약 |
|---|---|
| `notion-search` | 루트 또는 지정한 내부 페이지 하위 검색. 사용자 검색·데이터 소스·팀스페이스 추가 범위 지정은 거부 |
| `notion-fetch` | 페이지·DB·소스·뷰의 소속 검사. `self`와 `notion://docs/*`는 항상 허용 |
| `notion-create-pages` | 내부 페이지·DB·소스 부모 필수. 부모 생략·복수 부모·draft 생성 거부 |
| `notion-update-page` | 내부 페이지·DB 행 수정. 루트의 비어 있지 않은 `properties` 변경은 제목 변경 방지를 위해 거부. 루트 본문 수정은 허용 |
| `notion-move-pages` | 모든 원본과 목적지 검사 후 전달. 루트 이동·워크스페이스 최상위 이동 거부 |
| `notion-duplicate-page` | 내부 페이지·DB 행 복제. 루트와 DB 객체는 거부. 같은 부모 아래 복제되는 동작을 전제로 함 |
| `notion-create-database` | 내부 페이지 부모와 명시적 비관계형 DDL 스키마 필수. `database_type` 거부 |
| `notion-update-data-source` | 내부 단일 소스의 소속·기존 및 변경 스키마 검사. 관계형·롤업·미지원 타입·readOnly 속성 또는 `is_inline` 변경 거부 |
| `notion-create-view` | 목적지와 소스 검사. DB 탭은 소스가 해당 DB 소속인지 대조. 폼 생성·설정 거부 |
| `notion-update-view` | 참조 소스의 소속 검사. 배치 위치 검사 제외. 폼 설정 거부 |
| `notion-create-attachment` | 항상 허용. 페이지 경로 검사 없이 첨부 리소스 생성 |
| `notion-create-file-upload` | 항상 허용. 페이지 경로 검사 없이 업로드 URL 발급 |

공통 제약:

- 제목 기반 절대 경로가 정확하고 루트 이름이 유일하다는 전제다. 권한 검사 결과는 캐시하지 않는다.
- 소스는 소속 DB 경로와 소스 목록을 대조하며 단일 소스 구조만 지원한다. DB 객체 자체의 조회는 경로로 판정한다.
- 뷰 조회는 원본 DB의 뷰 목록 등재 여부도 검사한다. 뷰 수정은 합의한 범위에 따라 배치 검사를 제외한다.
- 폼 생성과 `configure`의 `FORM` 단어를 차단한다. 간단한 검사이므로 대소문자·인용 여부에 관계없이 같은 단어가 포함된 속성명·값도 거부한다. 기존 폼의 이름 변경은 허용한다.
- DB DDL은 지원 문법 전체를 대조한다. 기본 속성·선택·숫자·수식·고유 ID와 ADD/DROP/RENAME COLUMN, ALTER COLUMN SET 등을 지원하며 미지원 구문은 거부한다.
- 내부 하위 페이지·DB 삭제와 소스 휴지통 이동은 허용한다. 본문 변경으로 하위를 삭제하려면 `allow_deleting_content: true`를 지정한다.
- 항상 허용한 업로드도 입력 스키마와 Notion 자체 권한·파일 제한은 적용된다.
- 권한 검증 실패는 MCP 오류 `-32003`, 입력 스키마 위반은 `INVALID_PARAMS`로 거부한다.

구현: [notion_proxy/tool_functions.py](notion_proxy/tool_functions.py), [notion_proxy/permissions.py](notion_proxy/permissions.py).

## 의도적으로 제외한 범위

- **관계형 DB·롤업·외부 연결·다중 소스 DB:** DB 생성·스키마 수정에서 지원하지 않는다. 페이지 생성·수정에 전달한 관계 속성과 양방향 관계의 외부 영향은 별도 검사하지 않으므로 관계형 DB를 사용하지 않는 전제다.
- **템플릿 원본 권한:** 명시적 템플릿과 자동 적용 원본의 접근 권한은 검사하지 않는다.
- **동기화 블록:** 사용하지 않는 전제이며 외부 콘텐츠에 미치는 영향을 추적하지 않는다.
- **링크된 뷰의 배치 위치:** 내부 소스를 참조하면 외부 페이지의 뷰도 수정할 수 있다. 일반 링크·임베드 대상 페이지에 별도 읽기·쓰기 권한을 부여하는 기능은 없다.
- **반환 콘텐츠의 세부 필터링:** 허용 페이지 안의 멘션·링크·댓글 미리보기를 제거하지 않는다. 검색 결과별 경로 재검사는 하지 않고 Notion의 페이지 하위 검색 범위 제한을 신뢰한다.
- **동시 변경과 롤백:** 검사 이후 이동이나 비동기 실행 시점까지의 변경을 원자적으로 막지 않으며 원격 작업의 롤백을 보장하지 않는다.
- **비동기 작업 상태 조회:** 상태 조회 도구는 차단한다. `allow_async: false`도 항상 동기 완료를 보장하지 않으며 필요한 결과는 허용된 조회 또는 Notion에서 확인한다.
- **프록시 밖의 접근:** 토큰을 가진 프로그램의 직접 Notion 접속은 막지 않는다. 서명은 설정 변조를 탐지하지만 코드·공개키 교체나 과거 서명 설정으로의 되돌리기를 막지는 않는다.
- **완전한 MCP 중계·사용처 구현:** tools/list와 tools/call을 중계한다. resources/prompts·sampling·elicitation·진행 알림 전체 중계와 MCP 클라이언트 제품 구현은 범위 밖이다.

## 접근을 차단한 Notion MCP 도구

다음 **30개는 MCP 도구 목록에서 제외**한다. 이름을 알아도 호출은 거부되며 직접 Python 래퍼 호출도 동일하게 차단한다.

- `notion-ai-search`
- `notion-check-mcp-next-steps`
- `notion-convert-page-to-skill`
- `notion-create-comment`
- `notion-create-folder`
- `notion-download-attachment`
- `notion-get-async-task`
- `notion-get-comments`
- `notion-get-session-status`
- `notion-get-teams`
- `notion-get-users`
- `notion-list-favorite-pages`
- `notion-list-private-pages`
- `notion-list-recent-pages`
- `notion-list-session-events`
- `notion-list-shared-pages`
- `notion-query-data-sources`
- `notion-query-meeting-notes`
- `notion-query-multiple-data-sources`
- `notion-query-sessions`
- `notion-read-session-event`
- `notion-search-agents`
- `notion-search-sessions`
- `notion-search-skills`
- `notion-send-message-to-session`
- `notion-show-advanced-analysis-next-steps`
- `notion-spawn-session`
- `notion-stop-session`
- `notion-update-folder`
- `notion-wait-session`

차단 목록은 [notion_proxy/tool_runtime.py](notion_proxy/tool_runtime.py)의 `BLOCKED_TOOLS`에서 관리한다. [docs/notion_tools.json](docs/notion_tools.json)은 원본 참고 스냅샷이므로 차단한 도구도 보존한다.
