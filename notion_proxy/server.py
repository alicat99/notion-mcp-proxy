import argparse
import asyncio
import inspect
import json

import uvicorn
from jsonschema import ValidationError
from mcp.server import Server
from mcp.shared.exceptions import MCPError
from mcp.types import INVALID_PARAMS, CallToolResult, ListToolsResult, TextContent, Tool

from .lazy_upstream import AuthorizationRequired, LazyUpstream
from .tool_functions import NotionTools, TOOL_METHODS
from .tool_runtime import BLOCKED_TOOLS
from .signed_config import ROOT, load_config
from .upstream import connect_upstream


async def main():
    parser = argparse.ArgumentParser(description="Notion MCP bridge")
    parser.add_argument("--port", type=int, default=6378)
    parser.add_argument("--upstream", default="https://mcp.notion.com/mcp")
    parser.add_argument("--no-oauth", action="store_true")
    options = parser.parse_args()

    load_config()

    async def serve(tools, upstream, *, lazy=False):
        bridge = create_bridge(tools, upstream, lazy=lazy)
        print(f"Loaded {sum(tool.name in TOOL_METHODS and tool.name not in BLOCKED_TOOLS for tool in tools)} tools. "
              f"Bridge: http://127.0.0.1:{options.port}/mcp")
        config = uvicorn.Config(bridge.streamable_http_app(), host="127.0.0.1", port=options.port)
        await uvicorn.Server(config).serve()

    if options.no_oauth:
        async with connect_upstream(options.upstream) as upstream:
            await serve(await upstream.list_tools(), upstream)
    else:
        schema_path = ROOT / "docs" / "notion_tools.json"
        tools = [Tool.model_validate(tool) for tool in json.loads(schema_path.read_text(encoding="utf-8"))]
        upstream = LazyUpstream(options.upstream)
        try:
            await serve(tools, upstream, lazy=True)
        finally:
            await upstream.close()


def create_bridge(tools, upstream, *, lazy=False):
    wrappers = NotionTools(upstream, tools)
    live_schema = not lazy

    async def list_tools(ctx, params):
        return ListToolsResult(tools=wrappers.runtime.tools)

    async def call_tool(ctx, params):
        functions = wrappers.functions
        if params.name in BLOCKED_TOOLS:
            raise MCPError(-32003, "Tool access is disabled")
        if params.name not in functions:
            raise MCPError(INVALID_PARAMS, "Unknown tool")
        arguments = params.arguments or {}
        try:
            inspect.signature(functions[params.name]).bind(**arguments)
        except TypeError as error:
            raise MCPError(INVALID_PARAMS, "Invalid tool arguments") from error
        try:
            if not lazy:
                return await functions[params.name](**arguments)
            wrappers.runtime.validate(params.name, arguments)
            return await upstream.run(lambda session: invoke(session, params.name, arguments))
        except AuthorizationRequired as error:
            return CallToolResult(is_error=True, content=[TextContent(type="text", text=str(error))])
        except PermissionError as error:
            raise MCPError(-32003, str(error)) from error
        except ValidationError as error:
            path = ".".join(str(part) for part in error.absolute_path) or "arguments"
            raise MCPError(INVALID_PARAMS, f"Invalid tool arguments at {path}") from error

    async def invoke(session, name, arguments):
        nonlocal wrappers, live_schema
        if not live_schema:
            wrappers = NotionTools(upstream, await session.list_tools())
            live_schema = True
        if name not in wrappers.functions:
            raise MCPError(INVALID_PARAMS, "Tool is not available on the current Notion MCP server")
        # LazyUpstream serializes the full call, including its permission lookups.
        runtime = wrappers.runtime
        previous, runtime.upstream = runtime.upstream, session
        try:
            return await wrappers.functions[name](**arguments)
        finally:
            runtime.upstream = previous

    return Server("Notion MCP bridge", on_list_tools=list_tools, on_call_tool=call_tool)


if __name__ == "__main__":
    asyncio.run(main())
