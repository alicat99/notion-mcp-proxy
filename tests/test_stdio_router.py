import sys
import unittest

from mcp import Client
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.server import Server
from mcp.shared.exceptions import MCPError
from mcp.types import CallToolResult, ListToolsResult, TextContent, Tool

from notion_proxy.server import SERVER_NAME
from notion_proxy.signed_config import ROOT
from test_bridge import serve_http


class StdioRouterTests(unittest.IsolatedAsyncioTestCase):
    async def test_existing_proxy_relays_pages_tool_results_and_errors(self):
        tool = Tool(name="notion-fetch", input_schema={"type": "object"})
        calls = []
        approval = "Notion authorization is required.\nhttps://example.com/authorize"

        async def list_tools(ctx, params):
            if params.cursor:
                return ListToolsResult(tools=[])
            return ListToolsResult(tools=[tool], next_cursor="next-page")

        async def call_tool(ctx, params):
            calls.append((params.name, params.arguments))
            if params.name == "notion-forbidden":
                raise MCPError(-32003, "Tool access is disabled")
            return CallToolResult(is_error=True, content=[TextContent(type="text", text=approval)])

        backend = Server(SERVER_NAME, on_list_tools=list_tools, on_call_tool=call_tool)
        async with serve_http(backend) as url:
            port = url.split(":")[2].split("/")[0]
            launch = StdioServerParameters(
                command=sys.executable, cwd=ROOT,
                args=["-m", "notion_proxy.stdio_router", "--port", port],
            )
            async with Client(stdio_client(launch), read_timeout_seconds=15) as client:
                page = await client.list_tools()
                self.assertEqual(page.tools, [tool])
                self.assertEqual(page.next_cursor, "next-page")
                self.assertEqual((await client.list_tools(cursor=page.next_cursor)).tools, [])

                arguments = {"id": "테스트", "include_discussions": False}
                result = await client.call_tool(tool.name, arguments)
                self.assertTrue(result.is_error)
                self.assertEqual(result.content[0].text, approval)
                with self.assertRaises(MCPError) as denied:
                    await client.call_tool("notion-forbidden", {})
                self.assertEqual(denied.exception.code, -32003)
        self.assertEqual(calls, [("notion-fetch", arguments), ("notion-forbidden", {})])
