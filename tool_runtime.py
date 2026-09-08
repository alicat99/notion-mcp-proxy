"""Tool registration, argument validation and common upstream dispatch."""

import inspect

from jsonschema import validators

from permissions import Permissions


UNSET = object()
BLOCKED_TOOLS = frozenset({
    "notion-convert-page-to-skill",
    "notion-ai-search",
    "notion-search-skills",
    "notion-create-folder",
    "notion-update-folder",
    "notion-create-comment",
    "notion-get-comments",
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
        for tool in tools:
            if tool.name in BLOCKED_TOOLS:
                continue
            if tool.name not in method_names:
                raise ValueError(f"Add an explicit wrapper for new tool: {tool.name}")
            function = getattr(owner, method_names[tool.name])
            parameters = set(inspect.signature(function).parameters)
            if set(tool.input_schema.get("properties", {})) != parameters:
                raise ValueError(f"Update wrapper parameters for changed tool: {tool.name}")
            self.functions[tool.name] = function
            validator_class = validators.validator_for(tool.input_schema)
            validator_class.check_schema(tool.input_schema)
            self.validators[tool.name] = validator_class(tool.input_schema)

    async def call(self, name, arguments):
        arguments = self.validate(name, arguments)
        return await self.upstream.call_tool(name, arguments)

    def validate(self, name, arguments):
        if name in BLOCKED_TOOLS:
            raise PermissionError(f"Tool access denied: {name}")
        arguments = {key: value for key, value in arguments.items() if value is not UNSET}
        self.validators[name].validate(arguments)
        return arguments

