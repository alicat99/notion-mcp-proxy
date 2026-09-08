import asyncio
from contextlib import asynccontextmanager

import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from .oauth import create_oauth


@asynccontextmanager
async def connect_upstream(url, use_oauth=True):
    auth = create_oauth(url) if use_oauth else None
    async with httpx2.AsyncClient(auth=auth, timeout=120) as http_client:
        transport = streamable_http_client(url, http_client=http_client)
        async with Client(transport) as client:
            yield UpstreamClient(client)


class UpstreamClient:
    def __init__(self, client):
        self.client = client
        self.lock = asyncio.Lock()

    async def list_tools(self):
        tools = []
        cursor = None
        async with self.lock:
            while True:
                page = await self.client.list_tools(cursor=cursor)
                tools.extend(page.tools)
                cursor = page.next_cursor
                if not cursor:
                    return tools

    async def call_tool(self, name, arguments):
        # One OAuth connection must not refresh concurrently.
        async with self.lock:
            return await self.client.call_tool(name, arguments)
