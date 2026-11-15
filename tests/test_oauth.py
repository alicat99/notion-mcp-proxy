import asyncio
import base64
import hashlib
import json
import unittest
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import httpx2
from mcp import Client
from mcp.server import Server
from mcp.types import CallToolResult, ListToolsResult, TextContent, Tool
from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response
from starlette.routing import Mount, Route

from notion_proxy.lazy_upstream import LazyUpstream
from notion_proxy.oauth_callback import CALLBACK_PATH
from notion_proxy.server import create_bridge
from test_bridge import serve_http


UPLOAD = Tool(name="notion-create-file-upload", input_schema={
    "type": "object",
    "properties": {"filename": {"type": "string"}, "content_type": {"type": "string"}},
    "required": ["filename"],
})


class OAuthTests(unittest.IsolatedAsyncioTestCase):
    async def test_lazy_login_callback_retry_and_silent_refresh(self):
        credentials = {}
        counts = dict(upstream=0, registration=0, upload=0, refresh=0)
        token = None
        registered_redirect = None
        challenge = None
        reject_refresh = False
        tunnel_closed = asyncio.Event()
        callback_app = None
        origin = None

        async def list_tools(ctx, params):
            return ListToolsResult(tools=[UPLOAD])

        async def call_tool(ctx, params):
            counts["upload"] += 1
            return CallToolResult(content=[TextContent(type="text", text=params.arguments["filename"])])

        async def auth_metadata(request):
            return JSONResponse({
                "issuer": origin, "authorization_endpoint": origin + "/authorize",
                "token_endpoint": origin + "/token", "registration_endpoint": origin + "/register",
                "response_types_supported": ["code"], "code_challenge_methods_supported": ["S256"],
            })

        async def register(request):
            nonlocal registered_redirect
            counts["registration"] += 1
            metadata = await request.json()
            registered_redirect = metadata["redirect_uris"][0]
            return JSONResponse({**metadata, "client_id": "test-client"}, status_code=201)

        async def exchange(request):
            nonlocal token
            form = {key: values[0] for key, values in parse_qs((await request.body()).decode()).items()}
            self.assertEqual(form["client_id"], "test-client")
            if form["grant_type"] == "authorization_code":
                self.assertEqual(form["redirect_uri"], registered_redirect)
                self.assertEqual(form["code"], "mock-code")
                pkce = hashlib.sha256(form["code_verifier"].encode()).digest()
                self.assertEqual(base64.urlsafe_b64encode(pkce).decode().rstrip("="), challenge)
                token = "initial-token"
            else:
                self.assertEqual(form["grant_type"], "refresh_token")
                self.assertEqual(form["refresh_token"], "refresh-me")
                counts["refresh"] += 1
                if reject_refresh:
                    return JSONResponse({"error": "invalid_grant"}, status_code=400)
                token = "refreshed-token"
            return JSONResponse({"access_token": token, "token_type": "Bearer",
                                 "refresh_token": "refresh-me", "expires_in": 3600})

        remote_mcp = Server("oauth-test-notion", on_list_tools=list_tools, on_call_tool=call_tool)
        remote_mcp_app = remote_mcp.streamable_http_app()
        app = Starlette(routes=[
            Route("/.well-known/oauth-authorization-server", auth_metadata),
            Route("/register", register, methods=["POST"]),
            Route("/token", exchange, methods=["POST"]),
            Mount("/", app=remote_mcp_app),
        ], lifespan=lambda _: remote_mcp_app.router.lifespan_context(remote_mcp_app))

        async def require_token(request, call_next):
            counts["upstream"] += 1
            if request.url.path == "/mcp" and (not token or request.headers.get("authorization") != f"Bearer {token}"):
                return Response(status_code=401, headers={"WWW-Authenticate": "Bearer"})
            return await call_next(request)

        app.add_middleware(BaseHTTPMiddleware, dispatch=require_token)

        @asynccontextmanager
        async def tunnel(callback, executable):
            nonlocal callback_app
            tunnel_closed.clear()
            callback_app = Starlette(routes=[Route(CALLBACK_PATH, callback.handle)])
            exit_signal = asyncio.get_running_loop().create_future()
            try:
                yield f"https://mock-{counts['registration'] + 1}.trycloudflare.com" + CALLBACK_PATH, exit_signal
            finally:
                exit_signal.cancel()
                tunnel_closed.set()

        async with serve_http(SimpleNamespace(streamable_http_app=lambda: app)) as remote_url:
            origin = remote_url.removesuffix("/mcp")
            upstream = LazyUpstream(remote_url)
            try:
                with (
                    patch("notion_proxy.oauth.keyring.get_password", side_effect=lambda _, key: credentials.get(key)),
                    patch("notion_proxy.oauth.keyring.set_password", side_effect=lambda _, key, value: credentials.__setitem__(key, value)),
                    patch("notion_proxy.lazy_upstream.shutil.which", return_value="cloudflared"),
                    patch("notion_proxy.lazy_upstream.quick_tunnel", tunnel),
                ):
                    bridge = create_bridge([UPLOAD], upstream, lazy=True)
                    async with serve_http(bridge) as url, Client(url) as client:
                        self.assertEqual([tool.name for tool in (await client.list_tools()).tools], [UPLOAD.name])
                        self.assertEqual(counts["upstream"], 0)
                        self.assertEqual(credentials, {})
                        arguments = {"filename": "notes.txt"}
                        first = await client.call_tool(UPLOAD.name, arguments)
                        self.assertTrue(first.is_error)
                        again = await client.call_tool(UPLOAD.name, arguments)
                        self.assertEqual(first.content[0].text, again.content[0].text)
                        self.assertEqual(counts["registration"], 1)
                        self.assertEqual(counts["upload"], 0)
                        self.assertEqual(credentials, {})
                        auth_url = first.content[0].text.splitlines()[1]
                        query = parse_qs(urlsplit(auth_url).query)
                        self.assertEqual(query["redirect_uri"][0], registered_redirect)
                        challenge = query["code_challenge"][0]
                        async with httpx2.AsyncClient(
                            transport=httpx2.ASGITransport(app=callback_app), base_url="https://mock.trycloudflare.com",
                        ) as browser:
                            bad = await browser.get(CALLBACK_PATH, params={"state": "wrong", "code": "mock-code"})
                            self.assertEqual(bad.status_code, 400)
                            good = await asyncio.wait_for(browser.get(
                                CALLBACK_PATH, params={"state": query["state"][0], "code": "mock-code"},
                            ), 10)
                            self.assertEqual(good.status_code, 200)
                            replay = await browser.get(CALLBACK_PATH, params={"state": query["state"][0], "code": "mock-code"})
                            self.assertEqual(replay.status_code, 409)
                            self.assertEqual((await browser.get("/mcp")).status_code, 404)
                        await asyncio.wait_for(tunnel_closed.wait(), 10)
                        self.assertEqual(counts["upload"], 0)
                        result = await client.call_tool(UPLOAD.name, arguments)
                        self.assertFalse(result.is_error)
                        self.assertEqual(result.content[0].text, "notes.txt")
                        self.assertEqual(counts["upload"], 1)
                        expire_tokens(credentials)
                        result = await client.call_tool(UPLOAD.name, arguments)
                        self.assertFalse(result.is_error)
                        self.assertEqual(counts["refresh"], 1)
                        self.assertEqual(counts["registration"], 1)
                        self.assertEqual(counts["upload"], 2)

                        reject_refresh = True
                        expire_tokens(credentials)
                        saved = credentials.copy()
                        with self.assertLogs("notion_proxy.lazy_upstream", level="WARNING"):
                            result = await client.call_tool(UPLOAD.name, arguments)
                            self.assertTrue(result.is_error)
                            new_query = parse_qs(urlsplit(result.content[0].text.splitlines()[1]).query)
                            self.assertNotEqual(new_query["redirect_uri"], query["redirect_uri"])
                            self.assertEqual(counts["registration"], 2)
                            self.assertEqual(counts["upload"], 2)
                            async with httpx2.AsyncClient(
                                transport=httpx2.ASGITransport(app=callback_app), base_url="https://mock-2.trycloudflare.com",
                            ) as browser:
                                denied = await asyncio.wait_for(browser.get(CALLBACK_PATH, params={
                                    "state": new_query["state"][0], "error": "access_denied",
                                }), 10)
                                self.assertEqual(denied.status_code, 400)
                            await asyncio.wait_for(tunnel_closed.wait(), 10)
                        self.assertEqual(credentials, saved)
            finally:
                await upstream.close()


def expire_tokens(credentials):
    key = "tokens_" + credentials["credentials_slot"]
    data = json.loads(credentials[key])
    data["expires_at"] = 1.0
    credentials[key] = json.dumps(data)
