"""Tool registration, argument validation and common upstream dispatch."""

import inspect
import logging

from jsonschema import validators

from .permissions import Permissions


UNSET = object()
logger = logging.getLogger(__name__)
BLOCKED_TOOLS = frozenset({
    "notion-list-private-pages",
    "notion-list-shared-pages",
    "notion-list-favorite-pages",
    "notion-list-recent-pages",
    "notion-download-attachment",
    "notion-get-async-task",
    "notion-get-teams",
    "notion-get-users",
    "notion-show-advanced-analysis-next-steps",
    "notion-check-mcp-next-steps",

    "notion-convert-page-to-skill",
    "notion-ai-search",
    "notion-search-skills",
    "notion-create-folder",
    "notion-update-folder",
    "notion-create-comment",
    "notion-get-comments",
    "notion-query-meeting-notes",
    "notion-query-data-sources",
    "notion-query-multiple-data-sources",
    "notion-search-agents",
    "notion-search-sessions",
    "notion-query-sessions",
    "notion-spawn-session",
    "notion-get-session-status",
    "notion-wait-session",
    "notion-stop-session",
    "notion-send-message-to-session",
    "notion-list-session-events",
    "notion-read-session-event",
})


class ToolRuntime:
    def __init__(self, upstream, tools, owner, method_names):
        self.upstream = upstream
        self.permissions = Permissions(self.call)
        self.functions = {}
        self.validators = {}
        self.tools = []
        for tool in tools:
            if tool.name in BLOCKED_TOOLS:
                continue
            if tool.name not in method_names:
                logger.warning("Skipping unsupported new tool: %s. Add an explicit wrapper to enable it.", tool.name)
                continue
            function = getattr(owner, method_names[tool.name])
            parameters = set(inspect.signature(function).parameters)
            properties = set(tool.input_schema.get("properties", {}))
            added = properties - parameters
            if parameters - properties or added & set(tool.input_schema.get("required", [])):
                raise ValueError(f"Update wrapper parameters for changed tool: {tool.name}")
            exposed_tool = tool
            if added:
                logger.warning("Ignoring unsupported optional parameters for %s: %s. Update the wrapper to enable them.",
                               tool.name, ", ".join(sorted(added)))
                exposed_tool = tool.model_copy(deep=True)
                for parameter in added:
                    del exposed_tool.input_schema["properties"][parameter]
            self.functions[tool.name] = function
            validator_class = validators.validator_for(tool.input_schema)
            validator_class.check_schema(tool.input_schema)
            self.validators[tool.name] = validator_class(tool.input_schema)
            self.tools.append(exposed_tool)

    async def call(self, name, arguments):
        arguments = self.validate(name, arguments)
        return await self.upstream.call_tool(name, arguments)

    def validate(self, name, arguments):
        if name in BLOCKED_TOOLS:
            raise PermissionError(f"Tool access denied: {name}")
        arguments = {key: value for key, value in arguments.items() if value is not UNSET}
        self.validators[name].validate(arguments)
        return arguments

