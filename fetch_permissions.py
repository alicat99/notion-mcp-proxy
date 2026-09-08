"""Parse structural metadata in Notion MCP fetch responses; never scan page content."""

import json
import re
from uuid import UUID
from xml.etree import ElementTree


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
