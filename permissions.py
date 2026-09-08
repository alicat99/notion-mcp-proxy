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

    async def fetch(self, arguments):
        id = arguments["id"]
        uri = urlsplit(id)
        if id == "self" or (uri.scheme == "notion" and uri.netloc == "docs" and uri.path.startswith("/")):
            return await self.call("notion-fetch", arguments)
        if not self.root_path:
            raise PermissionError("Fetch root is not configured")
        result, entity = await self._fetch_entity(arguments)
        kind = entity["metadata"]["type"]
        if kind == "page":
            # path excludes the page itself; use ancestry to recognize the root.
            if "path" in entity:
                path = tuple(entity["path"].split(" / "))
            else:
                path = database_path(entity)
            self._check_path(path, entity["title"])
        elif kind == "database":
            self._check_path(database_path(entity), entity["title"])
        elif kind in {"data_source", "view"}:
            source = entity
            source_id = object_id(id)
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
            if sources != {source_id} or (kind == "view" and object_id(id) not in views):
                raise PermissionError("Cannot verify data source or view membership")
        else:
            raise PermissionError("Unsupported fetch entity type")
        return result

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
