"""Expose the local Notion HTTP proxy to clients that launch a stdio server."""

import argparse
import asyncio
import errno
import os
import subprocess
import sys
import tempfile
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path

import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.server import Server
from mcp.server.stdio import stdio_server

from .server import DEFAULT_PORT, SERVER_NAME
from .signed_config import ROOT

if os.name == "nt":
    import msvcrt
else:
    import fcntl


HOST = "127.0.0.1"
STARTUP_TIMEOUT = 20


async def main():
    parser = argparse.ArgumentParser(description="Route stdio MCP traffic to the shared local Notion proxy")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    options = parser.parse_args()
    if not 1 <= options.port <= 65535:
        parser.error("--port must be between 1 and 65535")

    try:
        await ensure_proxy(options.port)
        async with AsyncExitStack() as stack:
            http = await stack.enter_async_context(httpx2.AsyncClient(timeout=135, trust_env=False))
            transport = streamable_http_client(f"http://{HOST}:{options.port}/mcp", http_client=http)
            try:
                async with asyncio.timeout(10):
                    client = await stack.enter_async_context(Client(transport, read_timeout_seconds=130))
            except Exception as error:
                raise RuntimeError(f"Could not establish MCP on {HOST}:{options.port}: {error}") from error
            if not client.server_info or client.server_info.name != SERVER_NAME:
                raise RuntimeError(f"Port {options.port} is not serving the Notion MCP proxy.")
            router = create_router(client)
            async with stdio_server() as (read, write):
                await router.run(read, write, router.create_initialization_options())
    except (OSError, RuntimeError) as error:
        parser.exit(1, f"Notion stdio router: {error}\n")


def create_router(client):
    async def list_tools(ctx, params):
        return await client.list_tools(cursor=params.cursor, cache_mode="bypass")

    async def call_tool(ctx, params):
        return await client.call_tool(params.name, params.arguments)

    return Server("Notion MCP stdio router", on_list_tools=list_tools, on_call_tool=call_tool)


async def ensure_proxy(port):
    log_path = ROOT / ".private" / f"notion-proxy-{port}.log"
    try:
        async with asyncio.timeout(STARTUP_TIMEOUT):
            async with launch_lock(port):
                if await is_listening(port):
                    return
                process = start_proxy(port, log_path)
                while not await is_listening(port):
                    if process.poll() is not None:
                        raise RuntimeError(f"Proxy exited with code {process.returncode}. See {log_path}")
                    await asyncio.sleep(0.1)
    except TimeoutError as error:
        raise RuntimeError(f"Timed out waiting for proxy on port {port}. See {log_path}") from error


def start_proxy(port, log_path):
    log_path.parent.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, "-u", "-X", "utf8", "-m", "notion_proxy.server", "--port", str(port)]
    options = {"start_new_session": True}
    if os.name == "nt":
        options = {"creationflags": subprocess.DETACHED_PROCESS | subprocess.CREATE_BREAKAWAY_FROM_JOB}
    with log_path.open("ab") as log:
        try:
            return subprocess.Popen(
                command, cwd=ROOT, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                **options,
            )
        except OSError as error:
            if os.name == "nt" and error.winerror == 5:
                raise RuntimeError(
                    "Could not start the proxy as an independent Windows process. "
                    f"Start it from a separate PowerShell with: "
                    f"uv run --frozen python -m notion_proxy.server --port {port}"
                ) from error
            raise


async def is_listening(port):
    try:
        _, writer = await asyncio.open_connection(HOST, port)
    except ConnectionRefusedError:
        return False
    writer.close()
    await writer.wait_closed()
    return True


@asynccontextmanager
async def launch_lock(port):
    # The OS releases the lock even if the router exits without cleanup.
    path = Path(tempfile.gettempdir()) / f"notion-mcp-proxy-{port}.lock"
    with path.open("a+b") as lock:
        while True:
            try:
                if os.name == "nt":
                    msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as error:
                if error.errno not in (errno.EACCES, errno.EAGAIN):
                    raise
                await asyncio.sleep(0.1)
        yield


if __name__ == "__main__":
    asyncio.run(main())
