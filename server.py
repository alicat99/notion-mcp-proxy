from mcp.server import MCPServer

server = MCPServer("Local MCP playground")


@server.tool()
def echo(message: str):
    """Return the supplied message."""
    return message


@server.tool()
def add(a: float, b: float):
    """Add two numbers."""
    return a + b


if __name__ == "__main__":
    server.run(transport="streamable-http", host="127.0.0.1", port=8000)
