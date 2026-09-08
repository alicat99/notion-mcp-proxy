"""Live policy probes. Creates two unattached uploads; write probes must be denied."""

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mcp import Client
from mcp.shared.exceptions import MCPError

from notion_proxy.signed_config import load_config
from notion_proxy.tool_functions import TOOL_METHODS
from notion_proxy.tool_runtime import BLOCKED_TOOLS


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:6378/mcp")
    parser.add_argument("--outside-page", required=True)
    parser.add_argument("--database", required=True)
    parser.add_argument("--data-source", required=True)
    parser.add_argument("--view", required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    root = load_config()["fetch"]["root_id"]
    outside = args.outside_page
    db = args.database
    source = args.data_source
    view = args.view
    page = {"properties": {"title": "MCP denied probe"}}
    create_view = {"data_source_id": source, "name": "MCP denied probe", "type": "table"}
    cases = [
        ("notion-search", "outside page", {"query": "test", "page_url": outside}),
        ("notion-search", "user search", {"query": "test", "query_type": "user"}),
        ("notion-search", "source scope", {"query": "test", "data_source_url": source}),
        ("notion-search", "teamspace scope", {"query": "test", "teamspace_id": outside}),
        ("notion-fetch", "outside page", {"id": outside}),
        ("notion-fetch", "outside discussions", {"id": outside, "include_discussions": True}),
        ("notion-fetch", "outside transcript", {"id": outside, "include_transcript": True}),
        ("notion-create-pages", "outside parent", {"pages": [page], "parent": {"page_id": outside}}),
        ("notion-create-pages", "missing parent", {"pages": [page]}),
        ("notion-create-pages", "ambiguous parent", {"pages": [page], "parent": {"page_id": root, "database_id": db}}),
        ("notion-create-pages", "draft", {"pages": [page], "parent": {"page_id": root}, "creation_mode": "draft"}),
        ("notion-update-page", "outside target", {"page_id": outside, "command": "insert_content", "content": ""}),
        ("notion-update-page", "root title", {"page_id": root, "command": "update_properties", "properties": {"title": "test"}}),
        ("notion-update-page", "special ID", {"page_id": "self", "command": "insert_content", "content": ""}),
        ("notion-move-pages", "outside source", {"page_or_database_ids": [outside], "new_parent": {"page_id": root}}),
        ("notion-move-pages", "outside destination", {"page_or_database_ids": [root], "new_parent": {"page_id": outside}}),
        ("notion-move-pages", "root move", {"page_or_database_ids": [root], "new_parent": {"page_id": root}}),
        ("notion-move-pages", "workspace", {"page_or_database_ids": [root], "new_parent": {"type": "workspace"}}),
        ("notion-duplicate-page", "outside source", {"page_id": outside}),
        ("notion-duplicate-page", "root duplicate", {"page_id": root}),
        ("notion-create-database", "outside parent", {"parent": {"page_id": outside}, "schema": 'CREATE TABLE ("Name" TITLE)'}),
        ("notion-create-database", "missing parent", {"schema": 'CREATE TABLE ("Name" TITLE)'}),
        ("notion-create-database", "relation DDL", {"parent": {"page_id": root}, "schema": 'CREATE TABLE ("Name" TITLE, "Link" RELATION(\'' + source + '\'))'}),
        ("notion-update-data-source", "wrong entity type", {"data_source_id": outside, "title": "unchanged"}),
        ("notion-update-data-source", "layout change", {"data_source_id": source, "is_inline": True}),
        ("notion-update-data-source", "relation DDL", {"data_source_id": source, "statements": 'ADD COLUMN "Link" RELATION(\'' + source + '\')'}),
        ("notion-create-view", "outside destination", {**create_view, "parent_page_id": outside}),
        ("notion-create-view", "missing destination", create_view),
        ("notion-create-view", "ambiguous destination", {**create_view, "database_id": db, "parent_page_id": root}),
        ("notion-create-view", "form view", {**create_view, "database_id": db, "type": "form"}),
        ("notion-create-view", "FORM settings", {**create_view, "database_id": db, "configure": "FORM OPEN"}),
        ("notion-update-view", "FORM settings", {"view_id": view, "configure": "form permissions editor"}),
        ("notion-update-view", "missing v", {"view_id": "https://www.notion.so/" + db, "name": "unchanged"}),
        ("notion-update-view", "ambiguous v", {"view_id": "https://www.notion.so/" + db + "?v=" + view + "&v=" + root, "name": "unchanged"}),
        ("notion-update-view", "wrong entity type", {"view_id": outside, "name": "unchanged"}),
    ]
    results = []
    async with Client(args.url) as client:
        names = []
        cursor = None
        while True:
            tools = await client.list_tools(cursor=cursor)
            names.extend(tool.name for tool in tools.tools)
            cursor = tools.next_cursor
            if not cursor:
                break
        if set(names) != set(TOOL_METHODS) - BLOCKED_TOOLS:
            raise RuntimeError("Live tool inventory differs from local policy")
        for name, label, arguments in [(n, "blocked tool", {}) for n in sorted(BLOCKED_TOOLS)] + cases:
            try:
                result = await client.call_tool(name, arguments)
            except MCPError as error:
                passed = error.code == -32003
                detail = str(error)
            else:
                passed = False
                detail = "Unexpected upstream result; is_error=" + str(result.is_error)
            results.append({"tool": name, "case": label, "passed": passed, "detail": detail})
            print(name, label, "PASS" if passed else "FAIL", flush=True)
            if not passed:
                break
        if all(item["passed"] for item in results):
            for name, arguments in [
                ("notion-fetch", {"id": root}),
                ("notion-create-attachment", {"filename": "mcp-permission-probe.txt", "content": "permission policy test"}),
                ("notion-create-file-upload", {"filename": "mcp-permission-probe.txt", "content_type": "text/plain"}),
            ]:
                result = await client.call_tool(name, arguments)
                results.append({"tool": name, "case": "allowed control", "passed": not result.is_error})
                print(name, "allowed control", not result.is_error, flush=True)
    args.report.write_text(json.dumps({
        "time": datetime.now(timezone.utc).isoformat(), "server": args.url,
        "exposed": names, "results": results,
        "limits": ["Finite probes, not an exhaustive security proof", "No live external database/source/view fixture; covered by mock tests", "Two unattached upload resources created"],
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if not all(item["passed"] for item in results):
        raise SystemExit("Permission probe failed; see report")


if __name__ == "__main__":
    asyncio.run(main())
