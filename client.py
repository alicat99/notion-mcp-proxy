import argparse
import asyncio
import json
from pathlib import Path

import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from oauth import create_oauth


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8000/mcp")
    parser.add_argument("--oauth", action="store_true")
    parser.add_argument("--tool")
    parser.add_argument("--args-file", type=Path)
    options = parser.parse_args()
    auth = create_oauth(options.url) if options.oauth else None

    async with httpx2.AsyncClient(auth=auth, timeout=120) as http_client:
        transport = streamable_http_client(options.url, http_client=http_client)
        async with Client(transport) as client:
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
            # result = await client.call_tool("echo", {"message": "Hello"})
            # print(result.model_dump_json(indent=2, by_alias=True))


if __name__ == "__main__":
    asyncio.run(main())
