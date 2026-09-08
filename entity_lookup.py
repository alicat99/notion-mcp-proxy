"""Internal Notion fetch and entity response parsing."""

import json


async def fetch_entity(call, arguments):
    result = await call("notion-fetch", arguments)
    if result.is_error:
        raise PermissionError("Fetch target could not be verified")
    try:
        entity = json.loads(result.content[0].text)
        entity["metadata"]["type"]
    except (ValueError, KeyError, IndexError, AttributeError, TypeError) as error:
        raise PermissionError("Unrecognized fetch response") from error
    return result, entity

