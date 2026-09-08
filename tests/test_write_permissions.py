import json
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

from jsonschema import ValidationError
from mcp.types import CallToolResult, Tool

from permissions import object_id
from tool_functions import NotionTools
from test_fetch_permissions import DB, SOURCE, VIEW, database_text, response


ROOT = "a" * 32
CHILD = "b" * 32
OUTSIDE = "c" * 32
ROW = "d" * 32


class WritePermissionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        snapshot = Path(__file__).resolve().parents[1] / "notion_tools.json"
        tools = [Tool.model_validate(t) for t in json.loads(snapshot.read_text(encoding="utf-8"))]
        self.upstream = AsyncMock()
        self.wrapper = NotionTools(self.upstream, tools)
        self.wrapper.runtime.permissions.root_path = ("홈", "test")
        self.entities = {
            ROOT: response("page", path="홈", title="test"),
            CHILD: response("page", path="홈 / test", title="child"),
            OUTSIDE: response("page", path="홈", title="outside"),
            ROW: response("page", path="홈 / test / db", title="row"),
            object_id(DB): response("database", title="db", text=database_text()),
            object_id(SOURCE): response("data_source", url=DB),
            object_id(VIEW): response("view"),
        }
        self.result = CallToolResult(content=[])

        async def call(name, arguments):
            if name == "notion-fetch":
                return self.entities[object_id(arguments["id"])]
            return self.result

        self.upstream.call_tool.side_effect = call

    async def test_create_in_page_database_and_source(self):
        for parent in ({"page_id": ROOT}, {"database_id": DB}, {"data_source_id": SOURCE}):
            with self.subTest(parent=parent):
                arguments = {"pages": [{"properties": {"title": "새 페이지"}}], "parent": parent}
                self.assertIs(await self.wrapper.create_pages(**arguments), self.result)
                self.upstream.call_tool.assert_awaited_with("notion-create-pages", arguments)

    async def test_missing_outside_draft_and_ambiguous_parent_denied(self):
        for extra in (
            {}, {"parent": {"page_id": OUTSIDE}},
            {"parent": {"page_id": ROOT}, "creation_mode": "draft"},
            {"parent": {"page_id": ROOT, "database_id": DB}},
            {"parent": {"page_id": ROOT, "unknown_destination": OUTSIDE}},
        ):
            with self.subTest(extra=extra), self.assertRaises(PermissionError):
                await self.wrapper.create_pages(pages=[{}], **extra)
        self.assert_no_writes()

    async def test_source_owner_outside_and_multiple_sources_denied(self):
        for text in (
            database_text().replace('title="test"', 'title="outside"'),
            database_text().replace('</data-sources>', '<data-source url="{{collection://' + ROOT + '}}"/></data-sources>'),
        ):
            self.entities[object_id(DB)] = response("database", title="db", text=text)
            for parent in ({"database_id": DB}, {"data_source_id": SOURCE}):
                with self.subTest(parent=parent, text=text), self.assertRaises(PermissionError):
                    await self.wrapper.create_pages(pages=[{}], parent=parent)
        self.assert_no_writes()

    async def test_write_targets_reject_special_ids_and_wrong_types(self):
        for id in ("self", "notion://docs/test", DB, SOURCE, VIEW):
            with self.subTest(id=id), self.assertRaises(PermissionError):
                await self.wrapper.update_page(page_id=id, command="insert_content", content="x")
        for parent in ({"page_id": DB}, {"database_id": CHILD}, {"data_source_id": CHILD}):
            with self.subTest(parent=parent), self.assertRaises(PermissionError):
                await self.wrapper.create_pages(pages=[{}], parent=parent)
        self.assert_no_writes()

    async def test_update_page_row_and_root_content_allowed(self):
        for id in (ROOT, CHILD, ROW):
            arguments = {"page_id": id, "command": "replace_content", "new_str": "", "allow_deleting_content": True}
            self.assertIs(await self.wrapper.update_page(**arguments), self.result)
            self.upstream.call_tool.assert_awaited_with("notion-update-page", arguments)

    async def test_root_property_changes_and_outside_updates_denied(self):
        for arguments in (
            {"page_id": ROOT, "command": "update_properties", "properties": {"title": "renamed"}},
            {"page_id": ROOT, "command": "insert_content", "content": "x", "properties": {"title": None}},
            {"page_id": ROOT, "command": "update_properties", "properties": {"Name": "alias"}},
            {"page_id": OUTSIDE, "command": "replace_content", "new_str": ""},
        ):
            with self.subTest(arguments=arguments), self.assertRaises(PermissionError):
                await self.wrapper.update_page(**arguments)
        self.assert_no_writes()

    async def test_templates_relations_and_options_are_passed_through(self):
        await self.wrapper.create_pages(
            pages=[{"template_id": OUTSIDE}], parent={"page_id": ROOT}, allow_async=False,
        )
        await self.wrapper.update_page(page_id=CHILD, command="apply_template", template_id=OUTSIDE)
        arguments = {"page_id": ROW, "command": "update_properties", "properties": {"relation": [OUTSIDE], "value": None}, "allow_async": False}
        await self.wrapper.update_page(**arguments)
        self.upstream.call_tool.assert_awaited_with("notion-update-page", arguments)
        self.assertNotIn(OUTSIDE, [object_id(c.args[1]["id"]) for c in self.upstream.call_tool.await_args_list if c.args[0] == "notion-fetch"])

    async def test_move_validates_every_source_before_single_write(self):
        for parent in ({"page_id": ROOT}, {"database_id": DB}, {"data_source_id": SOURCE}):
            arguments = {"page_or_database_ids": [CHILD, ROW], "new_parent": parent}
            self.assertIs(await self.wrapper.move_pages(**arguments), self.result)
            self.upstream.call_tool.assert_awaited_with("notion-move-pages", arguments)
        await self.wrapper.move_pages(page_or_database_ids=[DB], new_parent={"page_id": ROOT})

    async def test_move_root_outside_mixed_batch_and_workspace_denied(self):
        for ids, parent in (
            ([ROOT], {"page_id": CHILD}),
            ([CHILD, OUTSIDE], {"page_id": ROOT}),
            ([CHILD], {"page_id": OUTSIDE}),
            ([CHILD], {"type": "workspace"}),
            ([CHILD], {"page_id": ROOT, "database_id": DB}),
            ([SOURCE], {"page_id": ROOT}),
        ):
            with self.subTest(ids=ids, parent=parent), self.assertRaises(PermissionError):
                await self.wrapper.move_pages(page_or_database_ids=ids, new_parent=parent)
        self.assert_no_writes()

    async def test_invalid_schema_is_rejected_before_lookup(self):
        with self.assertRaises(ValidationError):
            await self.wrapper.update_page(page_id=CHILD, command="invalid")
        with self.assertRaises(ValidationError):
            await self.wrapper.create_pages(pages="invalid", parent={"page_id": ROOT})
        with self.assertRaises(ValidationError):
            await self.wrapper.create_pages(pages=[{}], parent={"page_id": ROOT, "type": "workspace"})
        with self.assertRaises(ValidationError):
            await self.wrapper.move_pages(page_or_database_ids=[], new_parent={"page_id": ROOT})
        self.upstream.call_tool.assert_not_awaited()

    async def test_empty_root_denies_all_writes_before_lookup(self):
        self.wrapper.runtime.permissions.root_path = ()
        with self.assertRaises(PermissionError):
            await self.wrapper.create_pages(pages=[{}], parent={"page_id": ROOT})
        with self.assertRaises(PermissionError):
            await self.wrapper.update_page(page_id=CHILD, command="insert_content", content="x")
        with self.assertRaises(PermissionError):
            await self.wrapper.move_pages(page_or_database_ids=[CHILD], new_parent={"page_id": ROOT})
        self.upstream.call_tool.assert_not_awaited()

    async def test_failed_lookup_denies_write_and_paths_are_not_cached(self):
        await self.wrapper.update_page(page_id=CHILD, command="insert_content", content="x")
        self.upstream.call_tool.reset_mock()
        self.entities[CHILD] = response("page", path="outside", title="child")
        with self.assertRaises(PermissionError):
            await self.wrapper.update_page(page_id=CHILD, command="insert_content", content="x")
        self.entities[CHILD] = CallToolResult(content=[], is_error=True)
        with self.assertRaises(PermissionError):
            await self.wrapper.update_page(page_id=CHILD, command="insert_content", content="x")
        self.assert_no_writes()

    def assert_no_writes(self):
        self.assertTrue(all(c.args[0] == "notion-fetch" for c in self.upstream.call_tool.await_args_list))
