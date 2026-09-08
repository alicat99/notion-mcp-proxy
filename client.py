import argparse
import asyncio
import json
from pathlib import Path

from mcp import Client


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8000/mcp")
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
