"""Shared entity membership and root path permissions."""

import json
import re
import tomllib
from pathlib import Path
from uuid import UUID
from xml.etree import ElementTree

from entity_lookup import fetch_entity


class Permissions:
    def __init__(self, call):
        self.call = call
        config = tomllib.loads(Path(__file__).with_name("permissions.toml").read_text(encoding="utf-8"))
        self.root_path = tuple(config["fetch"]["root_path"])

    #region Access checks

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
            raise PermissionError("The allowed root cannot be moved")
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
