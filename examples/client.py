#region 사용 예시
# 서버 구현과 독립된 참고용 클라이언트다. 프로젝트 루트에서 실행한다.
# 먼저 별도 터미널에서 서버를 시작하고 OAuth 연결을 완료한다.
#   uv run --frozen python -X utf8 -m notion_proxy.server
# 클라이언트에서는 OAuth 로그인을 하지 않는다.
#
# 전체 도구 목록과 입력 스키마:
#   uv run --frozen python -X utf8 examples/client.py
# 연결 정보 조회:
#   uv run --frozen python -X utf8 examples/client.py --tool notion-fetch --args-file examples/notion-self.json
# 다른 포트에 연결:
#   uv run --frozen python -X utf8 examples/client.py --url http://127.0.0.1:6379/mcp
# 페이지 조회 (JSON 파일의 페이지 ID를 실제 값으로 바꾼다):
#   uv run --frozen python -X utf8 examples/client.py --tool notion-fetch --args-file examples/notion-page.json
# -X utf8은 Windows 한국어 입출력을 위한 옵션이다.
#
# tools[].name, description, inputSchema를 확인하고 인자 JSON 파일을 작성한다.
# 인자가 없으면 --args-file을 생략한다. 쓰기 도구도 같은 방식이며 실제 Notion에 반영된다.
# UTF-8/BOM JSON과 중첩 객체, 배열, false, null을 그대로 전달한다.
# 여러 도구를 같은 연결에서 호출하려면 아래 Additional calls 부분을 수정한다.
#   result = await client.call_tool("실제 도구 이름", {"실제 인자": "값"})
#   print(result.model_dump_json(indent=2, by_alias=True))
#
# MCP 결과의 content, structuredContent, isError 등을 SDK JSON 형태로 출력한다.
# 텍스트·이미지 콘텐츠를 별도로 재해석하지 않는다.
# isError: true인 결과도 그대로 출력하며 CLI 종료 코드와는 별개다.
# 알 수 없는 도구·스키마 위반은 INVALID_PARAMS, 권한 거부는 -32003으로 반환된다.
# 네트워크·MCP 오류를 숨기거나 쓰기 요청을 자동으로 재시도하지 않는다.
#endregion


import argparse
import asyncio
import json
from pathlib import Path

from mcp import Client


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:6378/mcp")
    parser.add_argument("--tool")
    parser.add_argument("--args-file", type=Path)
    options = parser.parse_args()
    async with Client(options.url) as client:
        if options.tool:
            arguments = (
                json.loads(options.args_file.read_text(encoding="utf-8-sig"))
                if options.args_file else {}
            )
            result = await client.call_tool(options.tool, arguments)
            print(result.model_dump_json(indent=2, by_alias=True))
        else:
            cursor = None
            while True:
                result = await client.list_tools(cursor=cursor)
                print(result.model_dump_json(indent=2, by_alias=True))
                cursor = result.next_cursor
                if not cursor:
                    break

        # Additional calls
        # result = await client.call_tool("notion-fetch", {"id": "self"})
        # print(result.model_dump_json(indent=2, by_alias=True))


if __name__ == "__main__":
    asyncio.run(main())
