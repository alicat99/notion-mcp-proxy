import argparse
import asyncio
import inspect

import uvicorn
from jsonschema import ValidationError
from mcp.server import Server
from mcp.shared.exceptions import MCPError
from mcp.types import INVALID_PARAMS, ListToolsResult

from tool_functions import BLOCKED_TOOLS, NotionTools
from upstream import connect_upstream


async def main():
    parser = argparse.ArgumentParser(description="Notion MCP bridge")
    parser.add_argument("--port", type=int, default=6378)
    parser.add_argument("--upstream", default="https://mcp.notion.com/mcp")
    parser.add_argument("--no-oauth", action="store_true")
    options = parser.parse_args()

    async with connect_upstream(options.upstream, not options.no_oauth) as upstream:
        tools = await upstream.list_tools()
        bridge = create_bridge(tools, upstream)
        app = bridge.streamable_http_app()
        print(f"Loaded {sum(tool.name not in BLOCKED_TOOLS for tool in tools)} tools. "
              f"Bridge: http://127.0.0.1:{options.port}/mcp")
        config = uvicorn.Config(app, host="127.0.0.1", port=options.port)
        await uvicorn.Server(config).serve()


def create_bridge(tools, upstream):
    functions = NotionTools(upstream, tools).functions

    async def list_tools(ctx, params):
        return ListToolsResult(tools=[tool for tool in tools if tool.name in functions])

    async def call_tool(ctx, params):
        if params.name in BLOCKED_TOOLS:
            raise MCPError(-32003, "Agent and session tools are disabled")
        if params.name not in functions:
            raise MCPError(INVALID_PARAMS, "Unknown tool")
        arguments = params.arguments or {}
        try:
            inspect.signature(functions[params.name]).bind(**arguments)
        except TypeError as error:
            raise MCPError(INVALID_PARAMS, "Invalid tool arguments") from error
        try:
            return await functions[params.name](**arguments)
        except PermissionError as error:
            raise MCPError(-32003, str(error)) from error
        except ValidationError as error:
            path = ".".join(str(part) for part in error.absolute_path) or "arguments"
            raise MCPError(INVALID_PARAMS, f"Invalid tool arguments at {path}") from error

    return Server("Notion MCP bridge", on_list_tools=list_tools, on_call_tool=call_tool)


if __name__ == "__main__":
    asyncio.run(main())
