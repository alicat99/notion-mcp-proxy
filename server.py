import argparse
import asyncio

import uvicorn
from jsonschema import ValidationError
from mcp.server import Server
from mcp.shared.exceptions import MCPError
from mcp.types import INVALID_PARAMS, ListToolsResult

from tool_functions import build_functions
from upstream import connect_upstream


async def main():
    parser = argparse.ArgumentParser(description="Notion MCP bridge")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--upstream", default="https://mcp.notion.com/mcp")
    parser.add_argument("--no-oauth", action="store_true")
    options = parser.parse_args()

    async with connect_upstream(options.upstream, not options.no_oauth) as upstream:
        tools = await upstream.list_tools()
        bridge = create_bridge(tools, upstream)
        app = bridge.streamable_http_app()
        print(f"Loaded {len(tools)} tools. Bridge: http://127.0.0.1:{options.port}/mcp")
        config = uvicorn.Config(app, host="127.0.0.1", port=options.port)
        await uvicorn.Server(config).serve()


def create_bridge(tools, upstream):
    functions = build_functions(tools, upstream)

    async def list_tools(ctx, params):
        return ListToolsResult(tools=tools)

    async def call_tool(ctx, params):
        if params.name not in functions:
            raise MCPError(INVALID_PARAMS, "Unknown tool")
        try:
            return await functions[params.name](**(params.arguments or {}))
        except ValidationError as error:
            path = ".".join(str(part) for part in error.absolute_path) or "arguments"
            raise MCPError(INVALID_PARAMS, f"Invalid tool arguments at {path}") from error

    return Server("Notion MCP bridge", on_list_tools=list_tools, on_call_tool=call_tool)


if __name__ == "__main__":
    asyncio.run(main())
