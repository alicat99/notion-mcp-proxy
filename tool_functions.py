from jsonschema import validators


def build_functions(tools, upstream):
    return {tool.name: build_function(tool, upstream) for tool in tools}


def build_function(tool, upstream):
    validator_class = validators.validator_for(tool.input_schema)
    validator_class.check_schema(tool.input_schema)
    validator = validator_class(tool.input_schema)

    async def invoke(**arguments):
        validator.validate(arguments)
        # Add page permission checks here, before the upstream call.
        return await upstream.call_tool(tool.name, arguments)

    invoke.__name__ = tool.name
    invoke.__doc__ = tool.description
    return invoke
