import json
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

from mcp.types import CallToolResult, Tool

from permissions import object_id
from tool_functions import NotionTools
from test_fetch_permissions import DB, SOURCE, VIEW, database_text, response


PAGE = "a" * 32
OUTSIDE = "b" * 32


class ViewPermissionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        snapshot = Path(__file__).resolve().parents[1] / "notion_tools.json"
        tools = [Tool.model_validate(t) for t in json.loads(snapshot.read_text(encoding="utf-8"))]
        self.upstream = AsyncMock()
        self.wrapper = NotionTools(self.upstream, tools)
        self.wrapper.runtime.permissions.root_path = ("홈", "test")
        self.entities = {
            PAGE: response("page", path="홈 / test", title="child"),
            OUTSIDE: response("page", path="홈", title="outside"),
            object_id(DB): response("database", title="db", text=database_text()),
            object_id(SOURCE): response("data_source", url=DB),
            object_id(VIEW): response("view", text='<view url="view://x">' + json.dumps({"dataSourceUrl": "collection://" + SOURCE}) + '</view>'),
        }
        self.result = CallToolResult(content=[])

        async def call(name, arguments):
            if name == "notion-fetch":
                return self.entities[object_id(arguments["id"])]
            return self.result

        self.upstream.call_tool.side_effect = call

    async def test_create_database_tab_and_linked_view(self):
        for destination in ({"database_id": DB}, {"parent_page_id": PAGE}):
            arguments = {"data_source_id": SOURCE, "name": "일정", "type": "calendar", "configure": 'CALENDAR BY "날짜"', **destination}
            self.assertIs(await self.wrapper.create_view(**arguments), self.result)
            self.upstream.call_tool.assert_awaited_with("notion-create-view", arguments)

    async def test_create_rejects_missing_ambiguous_outside_and_wrong_type_destination(self):
        for destination in ({}, {"database_id": DB, "parent_page_id": PAGE}, {"parent_page_id": OUTSIDE}, {"parent_page_id": DB}, {"database_id": PAGE}):
            with self.subTest(destination=destination), self.assertRaises(PermissionError):
                await self.wrapper.create_view(data_source_id=SOURCE, name="x", type="table", **destination)
        self.assert_no_writes()

    async def test_create_rejects_different_database_source(self):
        self.entities[OUTSIDE] = response("database", title="other", text=database_text())
        with self.assertRaises(PermissionError):
            await self.wrapper.create_view(data_source_id=SOURCE, database_id=OUTSIDE, name="x", type="table")
        self.assert_no_writes()

    async def test_update_normalizes_uuid_uri_and_url_to_same_view(self):
        for id in (VIEW, "view://" + VIEW, "https://www.notion.so/" + DB + "?v=" + VIEW):
            self.assertIs(await self.wrapper.update_view(view_id=id, name="새 이름"), self.result)
            self.upstream.call_tool.assert_awaited_with("notion-update-view", {"view_id": "view://" + VIEW, "name": "새 이름"})

    async def test_unlisted_linked_view_update_allowed_but_fetch_still_denied(self):
        self.entities[object_id(DB)] = response("database", title="db", text=database_text().replace(VIEW, PAGE))
        await self.wrapper.update_view(view_id=VIEW, configure='SORT BY "날짜" ASC')
        with self.assertRaises(PermissionError):
            await self.wrapper.fetch(id="view://" + VIEW)

    async def test_outside_or_multiple_sources_deny_both_operations(self):
        for text in (
            database_text().replace('title="test"', 'title="outside"'),
            database_text().replace('</data-sources>', '<data-source url="{{collection://' + PAGE + '}}"/></data-sources>'),
        ):
            self.entities[object_id(DB)] = response("database", title="db", text=text)
            with self.assertRaises(PermissionError):
                await self.wrapper.create_view(data_source_id=SOURCE, parent_page_id=PAGE, name="x", type="table")
            with self.assertRaises(PermissionError):
                await self.wrapper.update_view(view_id=VIEW, name="x")
        self.assert_no_writes()

    async def test_forms_denied_before_lookup(self):
        with self.assertRaises(PermissionError):
            await self.wrapper.create_view(data_source_id=SOURCE, database_id=DB, name="x", type="form")
        for configure in ("FORM OPEN", "form anonymous true", 'SHOW "Name";\nFORM PERMISSIONS editor'):
            with self.assertRaises(PermissionError):
                await self.wrapper.create_view(data_source_id=SOURCE, database_id=DB, name="x", type="table", configure=configure)
            with self.assertRaises(PermissionError):
                await self.wrapper.update_view(view_id=VIEW, configure=configure)
        self.upstream.call_tool.assert_not_awaited()

    async def test_invalid_urls_wrong_kind_and_failed_lookup_deny_update(self):
        for id in ("self", "https://www.notion.so/" + DB, "https://www.notion.so/" + DB + "?v=" + VIEW + "&v=" + PAGE, PAGE):
            with self.subTest(id=id), self.assertRaises(PermissionError):
                await self.wrapper.update_view(view_id=id, name="x")
        self.entities[object_id(VIEW)] = CallToolResult(content=[], is_error=True)
        with self.assertRaises(PermissionError):
            await self.wrapper.update_view(view_id=VIEW, name="x")
        self.assert_no_writes()

    def assert_no_writes(self):
        self.assertTrue(all(c.args[0] == "notion-fetch" for c in self.upstream.call_tool.await_args_list))
