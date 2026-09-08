# Notion MCP Python bridge

Notion MCP의 클라이언트이면서 로컬 MCP 서버로 동작하는 Python 브릿지다.
시작할 때 원격 도구 목록의 모든 페이지를 읽어 미리 작성된 Python 메서드에 연결하고,
같은 이름·설명·입력 스키마·출력 스키마를 로컬 MCP 클라이언트에 제공한다.
`notion-fetch`, `notion-create-pages`, `notion-update-page`, `notion-move-pages`에 공통 루트 경로 기반 권한 검사를 적용한다. 검색·DB 생성/수정·페이지 복제·뷰 생성/수정에도 아래 정책을 적용한다. 총 30개 도구는 목록에서 제외하고 접근을 거부한다.
노출되는 12개 도구 중 10개는 아래 권한 검사를 적용하고, 업로드 생성 2개는 명시적으로 항상 허용한다. 합의한 예외와 지원 범위는 아래에 정리했다.

```text
notion_proxy/client.py
  → tools/call {name, arguments}
notion_proxy/server.py                 MCP 요청 파싱 / 함수 선택 / MCP 응답
  → functions[name](**arguments)
notion_proxy/tool_functions.py         42개 명시적 Python 메서드 / 도구별 정책 적용
  → notion_proxy/tool_runtime.py       도구 등록 / JSON Schema 검사 / 공통 호출
  → notion_proxy/permissions.py        공통 소속 검사 / 부모·대상 검사
  → notion_proxy/entity_lookup.py      내부 fetch / 객체 응답 파싱
  → tool_runtime.call(name, arguments)
notion_proxy/upstream.py               SDK 연결 / 공통 tools/call 조립 / 전송 / 응답 수신
  → https://mcp.notion.com/mcp
```

도구별로 달라지는 것은 이름과 인자 JSON이다. 전송 형식은 공통이므로 `notion_proxy/upstream.py`에 분리했다.
`notion_proxy/tool_functions.py`의 `NotionTools` 클래스에 42개 도구가 각각 `async def`로 존재한다.
`fetch`, `search`, `create_pages`, `update_page`처럼 이름·인자·설명을 코드에서 직접 확인하고 수정한다.
필수 인자는 기본값 없이, 선택 인자는 `UNSET`으로 선언한다. 선택 인자를 생략하면 전송하지 않고,
명시적으로 전달한 `None`, `False`, 빈 목록은 보존한다. 단, 실제 값은 서버 스키마 검증을 통과해야 한다.
중첩 인자는 원래 JSON 구조를 유지한다. 예를 들어 `query_data_sources(data=...)`의 모드별 필드는 data 내부에 넣는다.

파일 하단의 `TOOL_METHODS`가 MCP 이름과 Python 메서드를 명시적으로 연결한다.
예: `notion-fetch` → `fetch`, `notion-create-pages` → `create_pages`.
새 함수를 런타임에 생성하거나 인자 제한 없는 함수를 대신 노출하지 않는다.

`docs/notion_tools.json`에는 2026-09-08 실제 Notion MCP의 tools/list로 받은 42개 도구의 설명과 전체 스키마를 저장했다.
도구 구현 시 참고하는 목록이며 런타임 권한·실행 가능 여부를 보장하지 않는다. 서버는 시작할 때 실시간 스키마를 사용한다.
이번 조회에서는 원격 도구 메타데이터만 저장했으며 OAuth 자격 증명은 포함하지 않았다.

## 폴더 구조

```text
notion_proxy/   서버·클라이언트·권한 검사·OAuth·서명 CLI Python 패키지
config/         서명된 설정, 공개키, 서명
.private/       개인키 (Git 제외, 배포 시 제외)
docs/          원본 Notion 도구 스키마
examples/      호출 인자와 Codex 연결 설정 예시
tests/         자동 테스트와 실제 서버 검사 스크립트
reports/       실제 서버 검사 결과
vendor/        공식 MCP Python SDK
```

프로젝트 루트에서 `python -m notion_proxy.server`처럼 모듈로 실행한다.
설정·키 경로는 코드 위치를 기준으로 찾는다. 기존 루트의 `server.py`, `client.py`, `sign_permissions.py`는 이동했으므로 이전 파일 실행 명령은 사용할 수 없다.

## 공통 허용 루트 설정

프로젝트의 `config/permissions.toml`에서 절대 제목 경로를 배열로 지정한다. 기존 설정과 호환되도록 `[fetch]` 이름을 유지하지만, 권한이 적용된 도구들은 모두 같은 루트를 사용한다.

```toml
[fetch]
root_path = ["홈", "test"]
```

루트 자체와 하위 페이지를 허용한다. 경로 구성요소를 비교하므로 `test-other`는 `test`의 하위로 취급하지 않는다.
기본값 `[]`는 객체 조회와 위 세 도구의 쓰기를 모두 거부한다. 설정은 서버 시작 시 읽으므로 변경 후 서버를 재시작한다.
직접 Python으로 사용할 때도 `NotionTools` 생성 시 같은 파일을 읽는다.

| fetch 대상 | 정책 |
|---|---|
| `self` | 항상 허용. 사용자 이메일 등 연결 정보 포함 |
| `notion://docs/*` | 항상 허용 |
| 일반 페이지·DB 행 | `path` 검사. 루트 자체는 부모 경로와 제목을 합쳐 비교 |
| 데이터베이스 | `ancestor-path`의 조상 제목으로 검사 |
| 데이터 소스 | 응답의 DB URL을 조회하고 DB 경로 및 소스 ID 대조 |
| 저장된 뷰 | `view://UUID` 사용. 소스→DB 추적 후 DB 경로·소스 ID·뷰 ID 대조 |
| 기타 종류·확인 실패 | 거부 |

권한 판정용 fetch는 서버 내부에서 수행하고, 허용 판정 후에만 최초 응답을 클라이언트에 반환한다.
`include_transcript`, `include_discussions`에도 같은 검사를 적용하며 원래 옵션과 응답을 유지한다.
내부 fetch 오류의 원문은 반환하지 않고 검증 실패로 처리한다. MCP 권한 거부 코드는 `-32003`이다.
권한 결과는 캐시하지 않는다.

현재 범위와 전제:

- 제목 기반 절대 경로가 정확하고 루트 이름이 유일하다는 전제다. UUID 기반 루트 고정 기능은 없다.
- 직접 생성한 단일 데이터 소스 DB에서 검증했다. 복수 데이터 소스의 소스·뷰 조회 및 DB를 부모로 하는 생성·이동은 거부한다. DB 객체 자체의 조회는 경로로 판정한다.
- 데이터 소스 응답의 DB URL을 소속 DB로 사용한다. 외부 링크·외부 동기화 소스에 대한 소유 관계 보장은 아직 검증하지 않았으므로 해당 구성은 지원 범위 밖이다.
- fetch는 뷰 ID가 추적한 DB의 뷰 목록에 없으면 거부한다. update-view는 아래 정책에 따라 이 배치 검사를 제외한다.
- 링크·임베드된 외부 페이지를 별도로 읽기 허용하지 않는다. 해당 페이지를 fetch하면 자체 경로로 검사한다.
- 허용된 페이지 응답 안의 링크·멘션·댓글 미리보기 등은 별도로 필터링하지 않는다. 동기화 블록은 사용하지 않는 전제다.
- 여러 내부 조회 사이에 Notion 구조가 바뀌는 경우를 원자적으로 방지하지는 못한다.
- 아래에 별도 정책이 없는 도구의 조회·수정 요청은 이 경로 검사로 제한되지 않는다.

## 설정 전자서명

`config/permissions.toml` 전체 바이트를 Ed25519로 서명한다. 서버는 OAuth 연결 전에 서명을 검증하며,
직접 Python 래퍼를 생성할 때도 검증한다. 파일·서명이 없거나 검증에 실패하면 시작을 중단한다.
현재 설정의 키 생성과 서명은 완료되어 있다. 자동 재서명이나 검증 우회 옵션은 없다.

| 파일 | 용도 | Git 포함 |
|---|---|---|
| `config/permissions.toml` | 승인된 설정 | 포함 |
| `config/permissions.sig` | 설정 서명 | 포함 |
| `config/permissions-public.pem` | 검증 공개키 | 포함 |
| `.private/permissions-private.pem` | 서명 개인키 | 제외 |

설정 변경 후 승인한 내용에 다시 서명한다. 개인키가 있는 관리 컴퓨터에서 실행한다.

```powershell
uv run --frozen python -X utf8 -m notion_proxy.sign_permissions
```

설정과 새 `config/permissions.sig`를 함께 배포·커밋하고 서버를 재시작한다. 주석·공백·줄바꿈 변경도 재서명이 필요하다.
`.gitattributes`는 설정의 줄바꿈 자동 변환을 막아 다른 OS에서도 서명한 바이트가 유지되도록 한다.

다른 컴퓨터에는 저장소의 추적 파일만 복사하면 된다. 개인키 없이 다음 명령으로 검증할 수 있다.

```powershell
uv sync --frozen
uv run --frozen python -X utf8 -m notion_proxy.sign_permissions --verify
uv run --frozen python -X utf8 -m notion_proxy.server
```

**파일 탐색기로 폴더를 통째로 복사하면 `.gitignore`는 적용되지 않는다. 이 경우 `.private` 폴더는 직접 제외한다.**
개인키는 별도로 백업한다. 이 파일은 암호 없이 저장되며 Git 제외가 파일 읽기 권한을 제한하는 것은 아니다.
서명은 설정 변조를 탐지하며, 서버 코드·공개키 교체나 과거에 서명된 설정으로의 되돌리기까지 막지는 않는다.

새 설치에서 키가 전혀 없을 때만 `python -m notion_proxy.sign_permissions --init`을 사용한다. 기존 개인키 또는 공개키가 있으면
덮어쓰기를 거부한다. 배포 컴퓨터에서 새 키를 만들 필요는 없다.

## 페이지 생성·수정·이동 정책

모든 쓰기는 스키마 검증 → 공통 소속 검사 → 도구별 제한 → 원격 요청 순서로 실행한다.
쓰기 도구가 `NotionTools.fetch()`를 호출하지 않는다. `notion_proxy/permissions.py`의 같은 객체 검사 로직을 사용하며,
내부 조회와 응답 파싱은 `notion_proxy/entity_lookup.py`를 공유한다. `fetch()`는 예외 처리·조회·검사 요청·결과 반환을
직접 수행한다. 이미 조회한 객체를 `Permissions.check_entity()`에 전달하므로 해당 객체를 다시 조회하지 않는다.
데이터 소스·뷰의 소속 판정에 필요한 추가 객체만 권한 계층에서 조회한다. 조회용 `self`·문서 URI 예외는 쓰기에 적용되지 않는다.

| 도구 | 검사 및 제한 |
|---|---|
| `notion-create-pages` | 명시적 `parent` 필수. 허용 루트 내부 부모만 허용. `creation_mode="draft"`는 목적지 동작 미확인으로 거부 |
| `notion-update-page` | 대상이 허용 루트 내부의 페이지인지 검사. 루트 자체의 비어 있지 않은 `properties` 변경은 제목 변경 방지를 위해 거부. 루트 본문·아이콘·커버 수정은 허용 |
| `notion-move-pages` | 목적지와 모든 원본을 검사한 뒤 한 번만 전달. 루트 자체 이동과 워크스페이스 최상위 이동은 거부. 원본은 페이지 또는 DB만 허용 |

생성의 `parent`와 이동의 `new_parent`는 다음 중 하나를 사용한다.

```json
{"page_id": "부모 페이지 UUID"}
```

```json
{"database_id": "부모 DB UUID"}
```

```json
{"data_source_id": "부모 데이터 소스 UUID"}
```

선택적인 `type`은 ID 키와 같은 값이어야 한다. 여러 목적지 키 또는 알 수 없는 추가 부모 필드는 거부한다.
`database_id` 부모는 단일 데이터 소스를 찾아 소속을 추가 검사한다. 데이터 소스 ID는 내부 조회 시
`collection://` URI로 변환하며 실제 쓰기 요청의 인자는 그대로 유지한다.

합의한 범위:

- 템플릿 원본 권한은 검사하지 않는다. 명시적 템플릿 ID도 그대로 전달한다.
- 양방향 관계에 따른 외부 변경은 이 프로젝트의 권한 보장 범위 밖이다. 관계 속성을 추가 검사하지 않는다.
- 하위 페이지·DB 삭제는 허용한다. 실제 삭제를 허용하려면 호출자가 `allow_deleting_content: true`를 지정한다.
- 링크·임베드만으로 외부 페이지의 쓰기 권한을 부여하지 않는다.
- `allow_async` 등 실행 옵션은 원래 값으로 전달한다. 검사 후 실행 시점까지의 동시 이동·변경을 원자적으로 막지는 못한다.
- 검사 실패 시 쓰기 요청을 보내지 않는다. Notion에 전달된 작업 자체의 원자성이나 실패 시 롤백을 보장하는 것은 아니다.

검증: 자동 테스트 40개 통과. HTTP 브릿지의 권한 거부 응답, 일반 페이지·DB·데이터 소스 부모,
행 수정, 루트 보호, 외부 대상·복합 이동 거부, 템플릿·삭제 옵션 전달을 가짜 상위 서버로 검증한다.
이번 쓰기 권한 구현에서 실제 Notion 데이터 생성·수정·이동은 실행하지 않았다.

## 검색·DB·복제 정책

핵심 검사는 `notion_proxy/permissions.py`, 도구별 검증→검사→전달 흐름은 `notion_proxy/tool_functions.py`에 있다.
기존 루트 경로 설정을 유지하고 검색에 필요한 ID를 `config/permissions.toml`에 추가했다.

```toml
[fetch]
root_path = ["홈", "test"]
root_id = "3d53192c101b801bbfaafa7c74b40cac"
```

`root_id`는 현재 테스트 루트의 ID다. 다른 루트를 사용하려면 두 값을 함께 변경하고 서버를 재시작한다.
검색 때마다 이 ID가 실제 루트 경로에 해당하는 페이지인지 확인한다. ID나 루트 경로 미설정·불일치는 거부한다.

| 도구 | 적용 정책 |
|---|---|
| `notion-search` | `page_url` 생략 시 루트 ID를 사용한다. 지정 시 루트 자체 또는 하위 페이지인지 검사한 뒤 입력한 검색 범위를 유지한다. 외부 페이지·DB 객체·잘못된 ID는 거부한다. 사용자 검색과 추가 범위 지정(`data_source_url`, `teamspace_id`, `filters.teamspace_ids`)은 거부한다. 그 외 검색 조건은 유지한다. |
| `notion-create-database` | 명시적인 내부 페이지 부모 필수. 직접 작성한 비관계형 `schema`만 허용하며 `database_type`은 거부한다. |
| `notion-update-data-source` | 내부 단일 소스 DB의 소속 검사. DB ID 입력도 실제 `collection://` ID로 변환해 전송한다. 기존 관계형·롤업·알 수 없는 타입·readOnly 속성이 있으면 수정 거부. |
| `notion-duplicate-page` | 내부 일반 페이지·DB 행만 허용. 루트 자체와 DB 객체는 거부한다. |

검색 결과별 경로 필터는 적용하지 않는다. Notion의 페이지 및 하위 검색 범위 제한을 신뢰하는 정책이다.
DB 스키마는 전체 DDL 구문을 허용 문법과 대조한다. 관계형·롤업, SQL 주석, 미지원 구문은 거부한다.
기본 속성, SELECT/MULTI_SELECT, NUMBER FORMAT, FORMULA, UNIQUE_ID PREFIX와 열 설명을 지원한다.
변경문은 ADD/DROP/RENAME COLUMN, ALTER COLUMN SET을 지원한다. 여러 변경문은 세미콜론으로 구분한다.
외부 연결 및 다중 소스 DB는 지원 범위 밖이다. `is_inline` 변경은 거부한다.
내부 데이터 소스의 제목·설명 변경과 `in_trash`는 허용한다. 열 삭제·타입 변경·휴지통 이동은 기존 데이터를 잃게 할 수 있다.

복제는 실제 테스트에서 같은 부모 아래 생성되는 동작을 기준으로 원본 위치를 검사한다.
하위 콘텐츠 및 관계형 데이터의 복제 부작용은 별도 검사하지 않으므로 관계형 DB를 사용하지 않는 전제다.
기존 create-pages/update-page의 템플릿·관계형 속성 전달 정책은 이번 변경에 포함하지 않는다.
댓글 도구를 차단해도 허용된 fetch의 include_discussions 옵션까지 차단하는 것은 아니다.

검증은 가짜 상위 서버의 HTTP 테스트와 Python 권한 테스트로 수행했다. 이번 변경에서 실제 Notion 쓰기는 실행하지 않았다.

## 뷰 생성·수정 정책

- `notion-create-view`: `database_id` 또는 `parent_page_id` 중 정확히 하나를 지정한다. 목적지와 데이터 소스 모두 허용 루트 내부여야 한다. DB 탭 생성은 해당 소스가 목적지 DB의 유일한 소스인지도 대조한다.
- `notion-update-view`: 뷰가 참조하는 데이터 소스의 소속 DB와 루트 경로를 검사한다. 합의한 범위에 따라 뷰의 배치 위치와 원본 DB의 뷰 목록 등재 여부는 검사하지 않는다. 따라서 내부 소스를 참조하는 외부 위치의 링크된 뷰도 수정 가능하다.
- 뷰 ID는 UUID, `view://UUID`, `https://…?v=UUID`를 지원한다. URL은 `v`가 정확히 하나 있어야 한다. 수정 요청에는 검사한 `view://UUID`를 하이픈을 포함한 UUID 형식으로 전달한다. 실제 Notion에서는 하이픈 없는 뷰 ID의 조회는 성공했으나 수정은 404를 반환했다.
- 폼 뷰 생성(`type: "form"`)과 `configure`의 `FORM` 설정은 거부한다. 단순한 검사를 위해 대소문자와 인용 여부에 관계없이 `FORM` 단어가 포함된 설정 문자열을 거부하므로, 같은 이름의 속성이나 값도 해당한다. 기존 폼 뷰의 이름 변경 자체는 차단하지 않는다.
- 필터·정렬 등 허용된 설정은 원문 그대로 전달한다. 기존 fetch의 뷰 목록 대조 정책은 유지한다.
- 단일 데이터 소스 범위를 유지하며, 소속을 확인하지 못하거나 내부 조회가 실패하면 쓰기를 전달하지 않는다.

뷰 테스트는 DB 탭·링크된 뷰 생성, 외부 대상 거부, 뷰 URL 정규화, 배치 검사 제외, 폼 설정 차단을 검증한다.
전체 차단 도구가 HTTP tools/list에서 제외되고 tools/call 및 직접 Python 호출에서도 거부되는지 확인한다.
추가 도구 차단 전인 2026-09-08 실제 서버에서는 도구 22개 노출·차단 20개 거부, 목적지 누락/중복·폼 설정·외부 부모 거부를 확인했다.
`홈/test/test database`에 `MCP 권한 테스트 완료 2026-09-08` 뷰를 생성하고 이름·정렬 변경 후 조회로 확인했다.
실제 테스트에서 발견한 뷰 ID의 하이픈 문제를 수정했고, 수정본은 임시 HTTP 브릿지에서 실제 Notion에 연결해 재검증했다.
실행 중인 6378 서버에 수정본을 적용하려면 재시작해야 한다. 테스트 뷰는 확인용으로 남겨 두었다.

## 설치

Python 3.13 이상과 uv가 필요하다. 프로젝트 루트에서 실행한다.

```powershell
Set-Location 'D:\AI Projects\notion-proxy'
uv sync --frozen
```

`vendor/python-sdk`는 공식 SDK를 일반 파일로 포함한 디렉토리다. 별도 클론·서브모듈 초기화는 필요 없다.

## 서버 실행: 터미널 A

```powershell
uv run --frozen python -X utf8 -m notion_proxy.server
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
기존 `notion_proxy/client.py --oauth` 방식은 제거했다.

## 최소 클라이언트: 터미널 B

전체 도구 목록과 입력 스키마:

```powershell
uv run --frozen python -X utf8 -m notion_proxy.client
```

연결 정보 읽기:

```powershell
uv run --frozen python -X utf8 -m notion_proxy.client --tool notion-fetch --args-file examples/notion-self.json
```

다른 포트의 브릿지에 연결:

```powershell
uv run --frozen python -X utf8 -m notion_proxy.client --url http://127.0.0.1:6379/mcp
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

먼저 이 프로젝트에서 `uv run --frozen python -X utf8 -m notion_proxy.server`를 실행하고 OAuth 및 도구 로딩을 완료한다.
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
uv run --frozen python -X utf8 -m notion_proxy.client --tool notion-fetch --args-file examples/notion-page.json
```

`examples/notion-page.json`의 페이지 ID를 실제 값으로 수정한 뒤 실행한다.
도구 이름은 서버가 실제로 반환한 값을 사용한다. 쓰기 도구도 같은 방법으로 호출하며 실제 Notion에 반영된다.
입력은 UTF-8/BOM JSON을 지원한다. 중첩 객체, 배열, false, null을 그대로 전달한다.

여러 도구를 같은 연결에서 연속 호출하려면 `notion_proxy/client.py`의 `# Additional calls` 부분을 수정한다.

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
from notion_proxy.tool_functions import NotionTools
from notion_proxy.upstream import connect_upstream

async def main():
    async with connect_upstream("https://mcp.notion.com/mcp") as upstream:
        tools = NotionTools(upstream, await upstream.list_tools())
        result = await tools.fetch(id="self")
        print(result.model_dump_json(indent=2, by_alias=True))

asyncio.run(main())
```

`notion_proxy/tool_functions.py`는 MCP 서버나 HTTP 프레임워크를 import하지 않는다.
`notion_proxy/tool_functions.py`에는 초기화 연결, 도구별 명시적 메서드와 `TOOL_METHODS` 목록이 있다.
도구 등록·스키마 검증·공통 전송은 `notion_proxy/tool_runtime.py`, 소속 판정은 `notion_proxy/permissions.py`, 내부 조회·객체 응답 파싱은 `notion_proxy/entity_lookup.py`에 둔다.
기존 `fetch_permissions.py`는 `notion_proxy/permissions.py`로 통합했다.
MCP 호출과 직접 Python 호출 모두 같은 도구 메서드와 권한 검사를 거친다.
`runtime.call()`은 내부 전송용이며 페이지 권한 검사를 자체 수행하지 않는다. 외부 호출자는 항상 도구 메서드를 사용한다.

새 도구 추가 방법:

1. 실제 tools/list의 이름·설명·inputSchema를 확인한다.
2. 클래스에 명시적인 async 메서드를 추가하고 필수·선택 인자를 선언한다.
3. 메서드에서 인자를 딕셔너리로 구성한다. 권한이 필요한 도구는 `runtime.validate()` 후 `runtime.permissions`로 검사하고, `runtime.call("원래 MCP 이름", arguments)`로 전달한다.
4. `TOOL_METHODS`에 MCP 이름과 메서드 이름을 등록한다.
5. `docs/notion_tools.json` 참고 스키마와 테스트를 업데이트하고 서버를 재시작한다.

서버에 새 도구가 생겼는데 명시적 메서드가 없으면 시작을 중단하고 도구 이름을 알려준다.
실시간 스키마의 최상위 인자 이름과 메서드 시그니처가 달라진 경우에도 수정할 도구를 알려준다.
이는 중간 브릿지와 코드상의 도구 목록이 서로 달라진 채 동작하는 것을 방지한다.

## 노출 도구 권한 점검

42개 원본 도구를 대조한 결과, 30개는 차단하고 아래 12개만 노출한다. 정책 분류가 빠진 도구는 없다.

| 도구 | 정책 |
|---|---|
| `notion-search` | 루트 ID·경로 검증, 검색 범위 제한 |
| `notion-fetch` | 객체 종류·소속 검사. `self`·문서 URI 예외 유지 |
| `notion-create-pages` | 생성 부모 검사 |
| `notion-update-page` | 대상 검사·루트 속성 변경 차단 |
| `notion-move-pages` | 원본·목적지 검사·루트 이동 차단 |
| `notion-duplicate-page` | 원본 검사·루트 복제 차단 |
| `notion-create-database` | 부모 및 허용 스키마 검사 |
| `notion-update-data-source` | 소속 및 기존·변경 스키마 검사 |
| `notion-create-view` | 목적지·데이터 소스 검사, 폼 생성·설정 차단 |
| `notion-update-view` | 데이터 소스 검사, 폼 설정 차단. 배치 위치는 책임 범위 밖 |
| `notion-create-attachment` | 항상 허용. 페이지 경로 검사 없음 |
| `notion-create-file-upload` | 항상 허용. 페이지 경로 검사 없음 |

업로드 생성 두 함수에는 항상 허용한다는 주석을 명시했다. 여기서 항상 허용은 브릿지의 페이지 권한 정책 기준이며,
입력 스키마·Notion 사용자 권한·파일 제한·호출 오류는 그대로 적용된다. 빈 루트 설정에서도 두 도구는 호출된다.
이 점검은 권한 처리 연결 여부에 대한 것이다. 템플릿·양방향 관계·동기화 블록·동시 변경 등 앞서 정한 예외는 유지한다.

## 미지원 도구 차단

`notion_proxy/tool_runtime.py`의 `BLOCKED_TOOLS`에 다음 30개를 명시했다.

- `notion-list-private-pages`
- `notion-list-shared-pages`
- `notion-list-favorite-pages`
- `notion-list-recent-pages`
- `notion-download-attachment`
- `notion-get-async-task`
- `notion-get-teams`
- `notion-get-users`
- `notion-show-advanced-analysis-next-steps`
- `notion-check-mcp-next-steps`
- `notion-convert-page-to-skill`
- `notion-ai-search`
- `notion-search-skills`
- `notion-create-folder`
- `notion-update-folder`
- `notion-create-comment`
- `notion-get-comments`
- `notion-query-meeting-notes`
- `notion-query-data-sources`
- `notion-query-multiple-data-sources`
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
원본 42개 도구가 그대로 노출되는 환경에서는 브릿지가 12개를 제공한다.
변경 적용에는 서버 재시작과 클라이언트의 도구 목록 갱신이 필요하다.
원본 docs/notion_tools.json은 상위 서버의 참고 스냅샷이므로 차단 도구도 보존한다.

## 연결과 지원 범위

- 서버 시작 시 발견한 도구 중 차단된 도구를 제외하고 명시적 메서드에 연결해 노출한다. 현재 연결에서 노출되지 않은 메서드는 호출할 수 없다. 도구 목록 변경은 재시작 시 반영하고, 새로운 도구·인자는 위 절차로 코드를 수정한다.
- 실제 실행 가능 여부는 Notion 사용자 권한·요금제에 따른다.
- 상위 연결 하나를 공유하며 요청을 직렬화한다. 토큰 동시 갱신을 피하기 위한 단일 프로세스 구성이다.
- 동일 OAuth 저장소를 쓰는 서버·직접 호출 스크립트를 동시에 실행하지 않는다. 프로세스 간 잠금은 없다.
- 로컬 서버는 `127.0.0.1`에만 바인딩한다. 하위 클라이언트 인증은 없으므로 같은 컴퓨터의 프로세스가 도구를 호출할 수 있다.
- tools/list와 tools/call을 중계한다. resources/prompts, sampling/elicitation 콜백, 진행 알림까지 중계하는 완전한 MCP 프록시는 아니다.
- 도구 반환값 안의 Notion 비동기 작업 ID는 그대로 반환하지만 `notion-get-async-task`는 차단되어 이 브릿지에서 상태를 조회할 수 없다. `allow_async: false`는 그대로 지원하지만 Notion이 대기 작업을 반환하는 경우까지 방지하지는 않는다. 필요한 결과는 허용된 fetch로 확인하거나 Notion에서 확인한다.
- 파일 업로드 도구가 별도 HTTP 업로드 URL을 반환하면 파일 전송은 호출자가 수행한다.
- 상위 서버 연결이 끊기면 서버를 재시작한다. 쓰기 중 연결이 끊겼다면 실제 반영 여부부터 확인한다.

## OAuth 저장과 초기화

`notion_proxy/oauth.py`는 공식 SDK의 `OAuthClientProvider`를 재사용한다.
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
uv run --frozen python -X utf8 -m notion_proxy.server --upstream http://127.0.0.1:9000/mcp --no-oauth
```

### 실제 서버 권한 검사

`tests/live_permissions.py`로 실행 중인 서버에 거부 요청과 허용 대조 요청을 보낼 수 있다.
페이지·뷰 등을 만드는 요청은 거부되어야 하며, 허용 대조 검사에서는 페이지에 연결하지 않은 업로드 2개를 생성한다.
예상과 다른 응답이 나오면 이후 쓰기 검사를 중단한다. 외부 페이지 ID는 허용 루트 밖의 실제 페이지를 지정한다.

```powershell
uv run --frozen python -X utf8 tests/live_permissions.py --outside-page 2043192c101b802db804d8a778715854 --database 3d53192c101b80dfb6dbe54fe1fd962e --data-source collection://3d53192c-101b-80d0-88b7-000b2d29a54f --view 3d53192c-101b-81ac-a44e-000cad8a2148 --report reports/live-permission-results.json
```

2026-09-08 서명 적용 후 재시작한 6378 서버에서 총 68건이 통과했다.
노출 도구 12개 대조, 차단 도구 30개의 직접 호출 거부, 권한 적용 도구 10개의 금지 입력 35건 거부,
루트 조회 및 업로드 생성 2개의 허용을 확인했다. 상세 결과는 `reports/live-permission-results.json`에 저장했다.
토큰·업로드 URL·반환 콘텐츠는 결과 파일에 저장하지 않는다.

외부 DB·데이터 소스·뷰의 실물 표본은 사용하지 않았으며 해당 소속 검사와 설정 서명 변조는
자동 테스트로 보완했다. 이는 검사한 사례의 결과이며, 모든 입력·동시 변경에 대한 보안 증명은 아니다.

## SDK 출처

- 공식 저장소: https://github.com/modelcontextprotocol/python-sdk
- 원본 커밋: `9972c21aa42054fb1450c5fc614761ed11847ec6` (2.2.0)
- SDK 실행 코드는 원본 유지. 일반 파일 통합을 위해 두 패키지의 pyproject.toml에서 Git 기반 버전 생성을 2.2.0으로 고정했다.
- MIT LICENSE를 vendor에 유지한다. vendor 수정도 루트 Git 저장소에서 관리한다.
- SDK는 로컬 editable 의존성이므로 vendor 코드 수정이 실행에 반영된다.
