import json
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

from jsonschema import ValidationError
from mcp.types import CallToolResult, Tool

from notion_proxy.permissions import object_id
from notion_proxy.tool_functions import NotionTools
from test_fetch_permissions import DB, SOURCE, VIEW, database_text, response


QUERY = "notion-query-data-sources"
SOURCE_URL = "collection://" + SOURCE
SECOND = "44444444-4444-4444-4444-444444444444"
SECOND_URL = "collection://" + SECOND
SECOND_DB = "55555555-5555-5555-5555-555555555555"


class QueryPermissionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        snapshot = Path(__file__).resolve().parents[1] / "docs" / "notion_tools.json"
        tools = [Tool.model_validate(tool) for tool in json.loads(snapshot.read_text(encoding="utf-8"))
                 if tool["name"] in (QUERY, "notion-fetch", "notion-query-multiple-data-sources")]
        self.upstream = AsyncMock()
        self.wrapper = NotionTools(self.upstream, tools)
        self.wrapper.runtime.permissions.root_path = ("홈", "test")
        self.entities = {
            object_id(DB): response("database", title="DB", text=database_text()),
            object_id(SECOND_DB): response("database", title="second", text=database_text().replace(SOURCE, SECOND)),
            object_id(SOURCE): response("data_source", url=DB),
            object_id(SECOND): response("data_source", url=SECOND_DB),
            object_id(VIEW): response("view", text='<view url="view://fixture">'
                                      + json.dumps({"dataSourceUrl": SOURCE_URL}) + '</view>'),
        }
        self.result = CallToolResult(content=[])

        async def call(name, arguments):
            if name == "notion-fetch":
                return self.entities[object_id(arguments["id"])]
            return self.result

        self.upstream.call_tool.side_effect = call

    async def test_rows_checks_source_before_forwarding(self):
        data = {"mode": "rows", "data_source_url": SOURCE_URL, "limit": 25}
        self.assertIs(await self.wrapper.query_data_sources(data=data), self.result)
        self.assertEqual([call.args for call in self.upstream.call_tool.await_args_list], [
            ("notion-fetch", {"id": SOURCE_URL}), ("notion-fetch", {"id": DB}),
            (QUERY, {"data": data}),
        ])

    async def test_view_queries_the_same_view_id_used_to_resolve_source(self):
        data = {"mode": "view", "view_url": f"https://www.notion.so/{SECOND_DB}?v={VIEW}",
                "start_cursor": "next", "archive_status": "archived"}
        await self.wrapper.query_data_sources(data=data)
        canonical = "view://" + VIEW
        self.assertEqual([call.args for call in self.upstream.call_tool.await_args_list], [
            ("notion-fetch", {"id": canonical}), ("notion-fetch", {"id": SOURCE_URL}),
            ("notion-fetch", {"id": DB}), (QUERY, {"data": data | {"view_url": canonical}}),
        ])

    async def test_sql_checks_every_declared_source_and_preserves_sql_and_bindings(self):
        data = {"data_source_urls": [SOURCE_URL, SECOND_URL],
                "query": f'SELECT a.url FROM "{SOURCE_URL}" AS a JOIN "{SECOND_URL}" AS b ON a.url = b.url WHERE a.url != ?',
                "params": ["x"]}
        for mode in ({}, {"mode": "sql"}):
            self.upstream.reset_mock()
            request = data | mode
            await self.wrapper.query_data_sources(data=request)
            self.assertEqual([call.args for call in self.upstream.call_tool.await_args_list], [
                ("notion-fetch", {"id": SOURCE_URL}), ("notion-fetch", {"id": DB}),
                ("notion-fetch", {"id": SECOND_URL}), ("notion-fetch", {"id": SECOND_DB}),
                (QUERY, {"data": request}),
            ])

    async def test_external_source_denied_in_all_modes(self):
        self.entities[object_id(SECOND_DB)] = response(
            "database", title="external", text=database_text().replace(SOURCE, SECOND).replace('title="test"', 'title="other"'),
        )
        self.entities[object_id(VIEW)] = response("view", text='<view url="view://fixture">'
                                                + json.dumps({"dataSourceUrl": SECOND_URL}) + '</view>')
        for data in (
            {"mode": "rows", "data_source_url": SECOND_URL},
            {"mode": "view", "view_url": f"https://www.notion.so/{DB}?v={VIEW}"},
            {"mode": "sql", "data_source_urls": [SOURCE_URL, SECOND_URL],
             "query": f'SELECT count(*) FROM "{SOURCE_URL}"'},
        ):
            with self.subTest(mode=data["mode"]), self.assertRaises(PermissionError):
                await self.wrapper.query_data_sources(data=data)
        self.assertTrue(all(call.args[0] == "notion-fetch" for call in self.upstream.call_tool.await_args_list))

    async def test_invalid_targets_modes_and_separate_sql_tool_are_blocked(self):
        for data in (
            {"mode": "rows", "data_source_url": SOURCE_URL + "?id=" + SECOND},
            {"mode": "view", "view_url": f"https://www.notion.so/{DB}?v={VIEW}&v={SECOND}"},
            {"mode": "view", "view_url": f"https://www.notion.so/{DB}?v=&v={VIEW}"},
            {"mode": "sql", "data_source_urls": [], "query": "SELECT 1"},
        ):
            with self.subTest(data=data), self.assertRaises(PermissionError):
                await self.wrapper.query_data_sources(data=data)
        with self.assertRaises(ValidationError):
            await self.wrapper.query_data_sources(data={
                "mode": "rows", "data_source_url": SOURCE_URL, "data_source_urls": [SECOND_URL],
            })
        with self.assertRaises(PermissionError):
            await self.wrapper.query_multiple_data_sources(query="SELECT 1", data_source_urls=[SOURCE_URL])
        self.upstream.call_tool.assert_not_awaited()
