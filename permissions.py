"""Shared object lookup and root path permissions."""

import json
import re
import tomllib
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID
from xml.etree import ElementTree


class Permissions:
    def __init__(self, call):
        self.call = call
        config = tomllib.loads(Path(__file__).with_name("permissions.toml").read_text(encoding="utf-8"))
        self.root_path = tuple(config["fetch"]["root_path"])

    #region Access checks

    async def fetch(self, arguments):
        id = arguments["id"]
        uri = urlsplit(id)
        if id == "self" or (uri.scheme == "notion" and uri.netloc == "docs" and uri.path.startswith("/")):
            return await self.call("notion-fetch", arguments)
        result, _, _ = await self._inspect(arguments)
        return result

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
        _, entity, _ = await self._inspect({"id": id}, {kinds[key]})
        if key == "database_id":
            # An implicit row destination must resolve to one verified source.
            sources, _ = database_members(entity)
            if len(sources) != 1:
                raise PermissionError("Database parent must have one data source")
            await self._inspect({"id": "collection://" + next(iter(sources))}, {"data_source"})

    async def require_target(self, id, kinds, *, allow_root=True):
        object_id(id)
        _, _, is_root = await self._inspect({"id": id}, kinds)
        if is_root and not allow_root:
            raise PermissionError("The allowed root cannot be moved")
        return is_root

    #endregion

    #region Object inspection

    async def _inspect(self, arguments, kinds=None):
        if not self.root_path:
            raise PermissionError("Permission root is not configured")
        result, entity = await self._fetch_entity(arguments)
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
            source_id = object_id(arguments["id"])
            if kind == "view":
                source_url = view_source(entity)
                source_id = object_id(source_url)
                _, source = await self._fetch_entity({"id": source_url})
            if source["metadata"]["type"] != "data_source":
                raise PermissionError("Cannot verify data source")
            _, database = await self._fetch_entity({"id": source["url"]})
            if database["metadata"]["type"] != "database":
                raise PermissionError("Cannot verify owning database")
            self._check_path(database_path(database), database["title"])
            sources, views = database_members(database)
            # Multiple/linked sources need an ownership contract not supplied by fetch.
            if sources != {source_id} or (kind == "view" and object_id(arguments["id"]) not in views):
                raise PermissionError("Cannot verify data source or view membership")
        else:
            raise PermissionError("Unsupported fetch entity type")
        return result, entity, is_root

    async def _fetch_entity(self, arguments):
        result = await self.call("notion-fetch", arguments)
        if result.is_error:
            raise PermissionError("Fetch target could not be verified")
        try:
            entity = json.loads(result.content[0].text)
            entity["metadata"]["type"]
        except (ValueError, KeyError, IndexError, AttributeError, TypeError) as error:
            raise PermissionError("Unrecognized fetch response") from error
        return result, entity

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
