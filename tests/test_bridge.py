import asyncio
import base64
import json
import socket
import sys
import unittest
from contextlib import asynccontextmanager

import uvicorn
from mcp import Client
from mcp.server import Server
from mcp.shared.exceptions import MCPError
from mcp.types import (
    INVALID_PARAMS,
    CallToolResult,
    ImageContent,
    ListToolsResult,
    TextContent,
    Tool,
)

from server import create_bridge
from tool_functions import build_functions
from upstream import connect_upstream


class BridgeTests(unittest.TestCase):
    def test_http_bridge_preserves_tools_arguments_results_and_errors(self):
        asyncio.run(check_bridge())


async def check_bridge():
    calls = []
    tools = [
        Tool(
            name="notion-test-complex",
            description="Nested arguments and mixed content",
            input_schema={
                "type": "object",
                "required": ["pages", "enabled"],
                "additionalProperties": False,
                "properties": {
                    "pages": {"type": "array", "items": {"type": "object"}},
                    "enabled": {"type": "boolean"},
                    "optional": {"type": ["string", "null"]},
                },
            },
        ),
        Tool(name="notion-test-error", input_schema={"type": "object"}),
    ]

    async def list_tools(ctx, params):
        if params.cursor:
            return ListToolsResult(tools=tools[1:])
        return ListToolsResult(tools=tools[:1], next_cursor="second-page")

    async def call_tool(ctx, params):
        calls.append((params.name, params.arguments))
        if params.name == "notion-test-error":
            return CallToolResult(
                content=[TextContent(type="text", text="upstream tool failure")],
                is_error=True,
            )
        return CallToolResult(
            content=[
                TextContent(type="text", text="한글 그대로"),
                ImageContent(type="image", data=base64.b64encode(b"image").decode(), mime_type="image/png"),
            ],
            structured_content=params.arguments,
        )

    remote = Server("fixture", on_list_tools=list_tools, on_call_tool=call_tool)
    async with serve_http(remote) as remote_url:
        async with connect_upstream(remote_url, use_oauth=False) as upstream:
            discovered = await upstream.list_tools()
            assert [tool.name for tool in discovered] == [tool.name for tool in tools]
            bridge = create_bridge(discovered, upstream)
            async with serve_http(bridge) as bridge_url:
                process = await asyncio.create_subprocess_exec(
                    sys.executable, "-X", "utf8", "client.py", "--url", bridge_url,
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=15)
                assert process.returncode == 0, stderr.decode("utf-8")
                assert len(json.loads(stdout)["tools"]) == 2
                process = await asyncio.create_subprocess_exec(
                    sys.executable, "-X", "utf8", "client.py", "--url", bridge_url,
                    "--tool", "notion-test-error",
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=15)
                assert process.returncode == 0, stderr.decode("utf-8")
                assert json.loads(stdout)["isError"] is True
                async with Client(bridge_url) as client:
                    exposed = await client.list_tools()
                    assert exposed.tools == discovered
                    arguments = {
                        "pages": [{"title": "테스트", "properties": {"tags": [1, False, None]}}],
                        "enabled": False,
                        "optional": None,
                    }
                    result = await client.call_tool(tools[0].name, arguments)
                    assert calls[-1] == (tools[0].name, arguments)
                    assert result.structured_content == arguments
                    assert result.content[0].text == "한글 그대로"
                    assert result.content[1].data == base64.b64encode(b"image").decode()
                    error = await client.call_tool(tools[1].name, {})
                    assert error.is_error
                    assert error.content[0].text == "upstream tool failure"
                    before = len(calls)
                    for name, arguments in [(tools[0].name, {"enabled": "invalid"}), ("unknown", {})]:
                        try:
                            await client.call_tool(name, arguments)
                        except MCPError as error:
                            assert error.code == INVALID_PARAMS
                        else:
                            raise AssertionError("Invalid request was accepted")
                    assert len(calls) == before

            functions = build_functions(discovered, upstream)
            result = await functions[tools[0].name](pages=[], enabled=True)
            assert result.structured_content == {"pages": [], "enabled": True}


@asynccontextmanager
async def serve_http(server):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        config = uvicorn.Config(server.streamable_http_app(), log_level="critical")
        runner = uvicorn.Server(config)
        task = asyncio.create_task(runner.serve(sockets=[listener]))
        try:
            async with asyncio.timeout(10):
                while not runner.started:
                    if task.done():
                        await task
                        raise RuntimeError("HTTP server stopped before startup")
                    await asyncio.sleep(0.01)
            yield f"http://127.0.0.1:{port}/mcp"
        finally:
            runner.should_exit = True
            await asyncio.wait_for(task, timeout=10)


if __name__ == "__main__":
    unittest.main()
