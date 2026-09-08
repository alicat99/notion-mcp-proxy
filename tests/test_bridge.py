import asyncio
import base64
import json
import socket
import sys
import unittest
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock

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
from tool_functions import NotionTools, TOOL_METHODS
from upstream import connect_upstream


class BridgeTests(unittest.TestCase):
    def test_every_discovered_notion_tool_has_an_explicit_method(self):
        snapshot = Path(__file__).resolve().parents[1] / "notion_tools.json"
        tools = [Tool.model_validate(item) for item in json.loads(snapshot.read_text(encoding="utf-8"))]
        wrapper = NotionTools(AsyncMock(), tools)
        self.assertEqual(set(wrapper.functions), set(TOOL_METHODS))
        self.assertEqual(len(set(TOOL_METHODS.values())), len(tools))

    def test_optional_arguments_preserve_omission_null_and_false(self):
        schema = {
            "type": "object",
            "required": ["id"],
            "properties": {
                "id": {"type": "string"},
                "include_transcript": {"type": ["boolean", "null"]},
                "include_discussions": {"type": ["boolean", "null"]},
            },
        }
        upstream = AsyncMock()
        wrapper = NotionTools(upstream, [Tool(name="notion-fetch", input_schema=schema)])
        asyncio.run(wrapper.fetch(id="self"))
        upstream.call_tool.assert_awaited_with("notion-fetch", {"id": "self"})
        asyncio.run(wrapper.fetch(id="self", include_transcript=None, include_discussions=False))
        upstream.call_tool.assert_awaited_with(
            "notion-fetch", {"id": "self", "include_transcript": None, "include_discussions": False}
        )

    def test_new_tools_and_changed_parameters_require_explicit_updates(self):
        with self.assertRaisesRegex(ValueError, "new tool"):
            NotionTools(AsyncMock(), [Tool(name="notion-new-tool", input_schema={"type": "object"})])
        with self.assertRaisesRegex(ValueError, "changed tool"):
            NotionTools(AsyncMock(), [Tool(name="notion-fetch", input_schema={"type": "object"})])

    def test_http_bridge_preserves_tools_arguments_results_and_errors(self):
        asyncio.run(check_bridge())


async def check_bridge():
    calls = []
    tools = [
        Tool(
            name="notion-create-pages",
            description="Nested arguments and mixed content",
            input_schema={
                "type": "object",
                "required": ["pages", "allow_async"],
                "additionalProperties": False,
                "properties": {
                    "pages": {"type": "array", "items": {"type": "object"}},
                    "allow_async": {"type": "boolean"},
                    "parent": {"type": ["object", "null"]},
                    "creation_mode": {"type": "string"},
                },
            },
        ),
        Tool(name="notion-check-mcp-next-steps", input_schema={"type": "object"}),
    ]

    async def list_tools(ctx, params):
        if params.cursor:
            return ListToolsResult(tools=tools[1:])
        return ListToolsResult(tools=tools[:1], next_cursor="second-page")

    async def call_tool(ctx, params):
        calls.append((params.name, params.arguments))
        if params.name == "notion-check-mcp-next-steps":
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
                    "--tool", "notion-check-mcp-next-steps",
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
                        "allow_async": False,
                        "parent": None,
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
                    for name, arguments in [(tools[0].name, {"allow_async": "invalid"}), ("unknown", {})]:
                        try:
                            await client.call_tool(name, arguments)
                        except MCPError as error:
                            assert error.code == INVALID_PARAMS
                        else:
                            raise AssertionError("Invalid request was accepted")
                    assert len(calls) == before

            functions = NotionTools(upstream, discovered)
            result = await functions.create_pages(pages=[], allow_async=True)
            assert result.structured_content == {"pages": [], "allow_async": True}


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
