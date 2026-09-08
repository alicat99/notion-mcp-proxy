"""Shared entity membership and root path permissions."""

import json
import re
import tomllib
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from uuid import UUID
from xml.etree import ElementTree

from entity_lookup import fetch_entity


SIMPLE_TYPES = frozenset({
    "title", "rich_text", "date", "people", "checkbox", "url", "email",
    "phone_number", "status", "files", "created_time", "last_edited_time",
    "created_by", "last_edited_by",
})


class Permissions:
    def __init__(self, call):
        self.call = call
        config = tomllib.loads(Path(__file__).with_name("permissions.toml").read_text(encoding="utf-8"))
        self.root_path = tuple(config["fetch"]["root_path"])
        self.root_id = config["fetch"].get("root_id", "")

    #region Access checks

    async def require_view_creation(self, arguments):
        require_view_config(arguments.get("configure", ""))
        if arguments["type"] == "form":
            raise PermissionError("Form views are unsupported")
        if ("database_id" in arguments) == ("parent_page_id" in arguments):
            raise PermissionError("Specify exactly one database or page destination")
        source_id = object_id(arguments["data_source_id"])
        source, _ = await self._inspect({"id": "collection://" + source_id}, {"data_source"})
        if "parent_page_id" in arguments:
            await self.require_target(arguments["parent_page_id"], {"page"})
        else:
            database_id = arguments["database_id"]
            database, _ = await self._inspect({"id": database_id}, {"database"})
            sources, _ = database_members(database)
            if sources != {source_id} or object_id(source["url"]) != object_id(database_id):
                raise PermissionError("Data source must belong to the destination database")

    async def require_view_update(self, arguments):
        require_view_config(arguments.get("configure", ""))
        self.require_root()
        id = view_id(arguments["view_id"])
        _, entity = await fetch_entity(self.call, {"id": id})
        if entity["metadata"]["type"] != "view":
            raise PermissionError("Unexpected target entity type")
        # Placement is outside the update policy; source ownership still applies.
        await self._inspect({"id": view_source(entity)}, {"data_source"})
        return id

    async def search_scope(self, arguments):
        self.require_root()
        if arguments.get("query_type", "internal") != "internal":
            raise PermissionError("User search is disabled")
        if "data_source_url" in arguments or "teamspace_id" in arguments or "teamspace_ids" in arguments.get("filters", {}):
            raise PermissionError("Additional search scopes are unsupported")
        if not self.root_id or not await self.require_target(self.root_id, {"page"}):
            raise PermissionError("Search root ID must match the configured root path")
        if "page_url" in arguments:
            await self.require_target(arguments["page_url"], {"page"})
            return arguments["page_url"]
        return self.root_id

    async def require_database_creation(self, arguments):
        parent = arguments.get("parent")
        if not isinstance(parent, dict) or "page_id" not in parent:
            raise PermissionError("Database creation requires a page parent")
        await self.require_parent(parent)
        if "database_type" in arguments or "schema" not in arguments:
            raise PermissionError("An explicit non-relational schema is required")
        require_ddl(arguments["schema"], create=True)

    async def require_source_update(self, arguments):
        if "is_inline" in arguments:
            raise PermissionError("Changing database layout is unsupported")
        entity, _ = await self._inspect({"id": arguments["data_source_id"]}, {"database", "data_source"})
        if entity["metadata"]["type"] == "database":
            sources, _ = database_members(entity)
            if len(sources) != 1:
                raise PermissionError("Database must have one data source")
            source_id = next(iter(sources))
            entity, _ = await self._inspect({"id": "collection://" + source_id}, {"data_source"})
        else:
            source_id = object_id(arguments["data_source_id"])
        match = re.search(r"<data-source-state>\s*(.*?)\s*</data-source-state>", entity["text"], re.S)
        try:
            properties = json.loads(match[1])["schema"].values()
            for prop in properties:
                if prop["type"] not in SIMPLE_TYPES | {"select", "multi_select", "number", "formula", "unique_id"} or prop.get("readOnly"):
                    raise PermissionError("Relational, synced or unknown schemas are unsupported")
        except (TypeError, ValueError, KeyError) as error:
            raise PermissionError("Cannot verify existing schema") from error
        if "statements" in arguments:
            require_ddl(arguments["statements"], create=False)
        return "collection://" + source_id

    async def require_parent(self, parent):
        kinds = {"page_id": "page", "database_id": "database", "data_source_id": "data_source"}
        if not isinstance(parent, dict):
            raise PermissionError("An explicit parent is required")
        keys = set(parent) - {"type"}
        if len(keys) != 1 or not keys <= kinds.keys():
            raise PermissionError("Specify exactly one page, database or data source parent")
        key = next(iter(keys))
        if parent.get("type", key) != key:
            raise PermissionError("Parent type does not match its ID")
        id = parent[key]
        object_id(id)
        if key == "data_source_id":
            id = "collection://" + object_id(id)
        entity, _ = await self._inspect({"id": id}, {kinds[key]})
        if key == "database_id":
            # An implicit row destination must resolve to one verified source.
            sources, _ = database_members(entity)
            if len(sources) != 1:
                raise PermissionError("Database parent must have one data source")
            await self._inspect({"id": "collection://" + next(iter(sources))}, {"data_source"})

    async def require_target(self, id, kinds, *, allow_root=True):
        object_id(id)
        _, is_root = await self._inspect({"id": id}, kinds)
        if is_root and not allow_root:
            raise PermissionError("The allowed root cannot be moved or duplicated")
        return is_root

    def require_root(self):
        if not self.root_path:
            raise PermissionError("Permission root is not configured")

    #endregion

    #region Object inspection

    async def _inspect(self, arguments, kinds=None):
        self.require_root()
        _, entity = await fetch_entity(self.call, arguments)
        is_root = await self.check_entity(arguments["id"], entity, kinds)
        return entity, is_root

    async def check_entity(self, id, entity, kinds=None):
        self.require_root()
        kind = entity["metadata"]["type"]
        if kinds is not None and kind not in kinds:
            raise PermissionError("Unexpected target entity type")
        is_root = False
        if kind == "page":
            # path excludes the page itself; use ancestry to recognize the root.
            if "path" in entity:
                path = tuple(entity["path"].split(" / "))
            else:
                path = database_path(entity)
            is_root = self._check_path(path, entity["title"])
        elif kind == "database":
            is_root = self._check_path(database_path(entity), entity["title"])
        elif kind in {"data_source", "view"}:
            source = entity
            source_id = object_id(id)
            if kind == "view":
                source_url = view_source(entity)
                source_id = object_id(source_url)
                _, source = await fetch_entity(self.call, {"id": source_url})
            if source["metadata"]["type"] != "data_source":
                raise PermissionError("Cannot verify data source")
            _, database = await fetch_entity(self.call, {"id": source["url"]})
            if database["metadata"]["type"] != "database":
                raise PermissionError("Cannot verify owning database")
            self._check_path(database_path(database), database["title"])
            sources, views = database_members(database)
            # Multiple/linked sources need an ownership contract not supplied by fetch.
            if sources != {source_id} or (kind == "view" and object_id(id) not in views):
                raise PermissionError("Cannot verify data source or view membership")
        else:
            raise PermissionError("Unsupported fetch entity type")
        return is_root

    def _check_path(self, ancestors, title):
        root = self.root_path
        if ancestors[:len(root)] != root and ancestors + (title,) != root:
            raise PermissionError("Fetch target is outside the allowed root")
        return ancestors + (title,) == root

    #endregion


#region Response parsing


def view_id(value):
    uri = urlsplit(value)
    if uri.scheme in {"http", "https"}:
        values = parse_qs(uri.query).get("v", [])
        if len(values) != 1:
            raise PermissionError("View URL must contain exactly one v parameter")
        value = values[0]
    return "view://" + object_id(value)


def require_view_config(configure):
    if re.search(r"\bFORM\b", configure, re.I):
        raise PermissionError("FORM configuration is unsupported")


def database_path(entity):
    text = entity["text"]
    header = text.split("<ancestor-path>", 1)
    if len(header) != 2 or "<content>" in header[0]:
        raise PermissionError("Missing ancestor metadata")
    fragment = header[1].split("</ancestor-path>", 1)[0]
    try:
        ancestors = ElementTree.fromstring("<ancestors>" + fragment + "</ancestors>")
        return tuple(node.attrib["title"] for node in reversed(list(ancestors)))
    except (ElementTree.ParseError, KeyError) as error:
        raise PermissionError("Unrecognized ancestor metadata") from error


def database_members(entity):
    text = entity["text"]
    sources = section_ids(text, "data-sources", "data-source", "collection")
    views = section_ids(text, "views", "view", "view")
    return sources, views


def view_source(entity):
    match = re.search(r'<view\s+url="[^"]+">\s*(\{.*\})\s*</view>', entity["text"], re.S)
    try:
        return json.loads(match[1])["dataSourceUrl"].strip("{}")
    except (TypeError, ValueError, KeyError) as error:
        raise PermissionError("Missing view data source") from error


def section_ids(text, section, tag, scheme):
    match = re.search(fr"<{section}>(.*?)</{section}>", text, re.S)
    if not match:
        raise PermissionError("Missing database membership metadata")
    return {object_id(value) for value in re.findall(
        fr'<{tag}\s+url="\{{\{{{scheme}://([0-9a-fA-F-]+)\}}\}}"', match[1]
    )}


def object_id(value):
    match = re.search(r"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}|[0-9a-fA-F]{32})(?:[?/#]|$)", value)
    if not match:
        raise PermissionError("Unrecognized entity ID")
    return UUID(match[1]).hex

#endregion


#region Schema policy


def require_ddl(statement, *, create):
    # Match the complete supported grammar; quoted descriptions are not SQL keywords.
    name = r'"(?:[^"\\]|"")+"'
    string = r"'(?:[^'\\]|'')*'"
    colors = "default|gray|brown|orange|yellow|green|blue|purple|pink|red"
    option = fr"{string}(?:\s*:\s*(?:{colors}))?"
    options = fr"{option}(?:\s*,\s*{option})*"
    simple = "|".join(sorted(SIMPLE_TYPES))
    kind = fr"(?:(?:{simple})|NUMBER(?:\s+FORMAT\s+{string})?|(?:SELECT|MULTI_SELECT)\s*\(\s*(?:{options})?\s*\)|FORMULA\s*\(\s*{string}\s*\)|UNIQUE_ID(?:\s+PREFIX\s+{string})?)"
    column = fr"{name}\s+{kind}(?:\s+COMMENT\s+{string})?"
    if create:
        grammar = fr"\s*CREATE\s+TABLE\s*\(\s*{column}(?:\s*,\s*{column})*\s*\)\s*;?\s*"
    else:
        command = fr"(?:ADD\s+COLUMN\s+{column}|DROP\s+COLUMN\s+{name}|RENAME\s+COLUMN\s+{name}\s+TO\s+{name}|ALTER\s+COLUMN\s+{name}\s+SET\s+{kind})"
        grammar = fr"\s*{command}(?:\s*;\s*{command})*\s*;?\s*"
    if not re.fullmatch(grammar, statement, re.I):
        raise PermissionError("Unsupported DDL; relations and rollups are disabled")


#endregion
