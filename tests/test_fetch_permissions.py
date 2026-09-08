import json
import unittest
from unittest.mock import AsyncMock
from pathlib import Path

from mcp.types import CallToolResult, TextContent, Tool

from tool_functions import NotionTools


SOURCE = "11111111-1111-1111-1111-111111111111"
VIEW = "22222222-2222-2222-2222-222222222222"
DB = "33333333-3333-3333-3333-333333333333"


class FetchPermissionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        snapshot = Path(__file__).resolve().parents[1] / "notion_tools.json"
        tools = [Tool.model_validate(t) for t in json.loads(snapshot.read_text(encoding="utf-8"))]
        self.upstream = AsyncMock()
        self.wrapper = NotionTools(self.upstream, tools)
        self.wrapper.runtime.permissions.root_path = ("홈", "test")

    async def test_page_root_child_and_prefix_collision(self):
        for path, title, allowed in [
            ("홈", "test", True),
            ("홈 / test", "child", True),
            ("홈 / test / database", "row", True),
            ("홈 / test-other", "child", False),
            ("홈", "other", False),
        ]:
            with self.subTest(path=path, title=title):
                result = response("page", path=path, title=title)
                self.upstream.call_tool.return_value = result
                if allowed:
                    self.assertIs(await self.wrapper.fetch(id=DB), result)
                else:
                    with self.assertRaises(PermissionError):
                        await self.wrapper.fetch(id=DB)

    async def test_special_ids_and_unconfigured_root(self):
        self.wrapper.runtime.permissions.root_path = ()
        for id in ("self", "notion://docs/enhanced-markdown-spec"):
            await self.wrapper.fetch(id=id)
        self.upstream.reset_mock()
        for id in (DB, "https://example.com", "notion://other/docs"):
            with self.assertRaises(PermissionError):
                await self.wrapper.fetch(id=id)
        self.upstream.call_tool.assert_not_awaited()

    async def test_database_source_and_view(self):
        database = response("database", title="db", text=database_text())
        source = response("data_source", url=DB)
        view = response("view", text='<view url="view://x">' + json.dumps({
            "dataSourceUrl": "{{collection://" + SOURCE + "}}"
        }) + '</view>')
        for id, results in [
            (DB, [database]), (SOURCE, [source, database]),
            ("view://" + VIEW, [view, source, database]),
        ]:
            with self.subTest(id=id):
                self.upstream.call_tool.side_effect = results
                self.assertIs(await self.wrapper.fetch(id=id), results[0])

    async def test_outside_database_and_unlisted_view_denied(self):
        source = response("data_source", url=DB)
        view = response("view", text='<view url="view://x">' + json.dumps({
            "dataSourceUrl": "collection://" + SOURCE
        }) + '</view>')
        for text in (database_text().replace('title="test"', 'title="other"'),
                     database_text().replace(VIEW, DB),
                     database_text().replace(SOURCE, DB)):
            self.upstream.call_tool.side_effect = [view, source, response("database", title="db", text=text)]
            with self.assertRaises(PermissionError):
                await self.wrapper.fetch(id="view://" + VIEW)

    async def test_errors_and_unknown_entities_do_not_escape(self):
        for result in (CallToolResult(is_error=True, content=[TextContent(type="text", text="secret")]),
                       response("folder"), response("page", title="x", text="missing ancestors"),
                       CallToolResult(content=[TextContent(type="text", text="invalid json")])):
            self.upstream.call_tool.return_value = result
            with self.assertRaises(PermissionError):
                await self.wrapper.fetch(id=DB)


def response(kind, **fields):
    return CallToolResult(content=[TextContent(type="text", text=json.dumps({
        "metadata": {"type": kind}, **fields
    }))])


def database_text():
    return (
        '<database><ancestor-path><parent-page title="test"/>'
        '<ancestor-2-page title="홈"/></ancestor-path>'
        '<data-sources><data-source url="{{collection://' + SOURCE + '}}"/></data-sources>'
        '<views><view url="{{view://' + VIEW + '}}"/></views></database>'
    )
