"""Short-lived public listener for the OAuth browser callback."""

import asyncio
import hmac
import re
import socket
import subprocess
from contextlib import asynccontextmanager, nullcontext
from urllib.parse import parse_qs, urlsplit

import uvicorn
from mcp.client.auth import AuthorizationCodeResult
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route


CALLBACK_PATH = "/oauth/callback"
TUNNEL_URL = re.compile(rb"https://[a-z0-9-]+\.trycloudflare\.com(?=\s|\||$)")
RESPONSE_HEADERS = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}


class OAuthCallback:
    def __init__(self, publish_url):
        self.publish_url = publish_url
        self.state = None
        self.code = asyncio.get_running_loop().create_future()
        self.finished = asyncio.get_running_loop().create_future()

    async def redirect(self, url):
        self.state = parse_qs(urlsplit(url).query)["state"][0]
        self.publish_url(url)

    async def receive(self):
        result = await self.code
        if result is None:
            await asyncio.Future()  # The coordinator handles denial and cancels the SDK request.
        return result

    async def handle(self, request):
        params = request.query_params
        states = params.getlist("state")
        if (not self.state or len(states) != 1
                or not hmac.compare_digest(states[0].encode(), self.state.encode())):
            return PlainTextResponse("Invalid or expired authorization request.", 400, headers=RESPONSE_HEADERS)
        if self.code.done():
            return PlainTextResponse("Authorization callback already received.", 409, headers=RESPONSE_HEADERS)
        code, error, issuer = (params.getlist(key) for key in ("code", "error", "iss"))
        if len(issuer) > 1 or not ((len(code) == 1 and code[0] and not error)
                                   or (len(error) == 1 and error[0] and not code)):
            return PlainTextResponse("Invalid authorization response.", 400, headers=RESPONSE_HEADERS)
        self.code.set_result(AuthorizationCodeResult(
            code=code[0], state=states[0], iss=issuer[0] if issuer else None,
        ) if code else None)
        if await asyncio.shield(self.finished):
            return PlainTextResponse("Notion connected. Return to the MCP client and retry.", headers=RESPONSE_HEADERS)
        return PlainTextResponse("Notion authorization failed. Start again from the MCP client.", 400,
                                 headers=RESPONSE_HEADERS)


@asynccontextmanager
async def quick_tunnel(callback, executable):
    app = Starlette(routes=[Route(CALLBACK_PATH, callback.handle)])
    server = CallbackServer(uvicorn.Config(
        app, log_level="warning", access_log=False, timeout_graceful_shutdown=3,
    ))
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        serving = asyncio.create_task(server.serve(sockets=[listener]))
        process = reader = exited = None
        try:
            while not server.started:
                if serving.done():
                    serving.result()
                    raise RuntimeError("OAuth callback listener did not start")
                await asyncio.sleep(0.01)
            process = await asyncio.create_subprocess_exec(
                executable, "tunnel", "--url", f"http://127.0.0.1:{port}", "--no-autoupdate",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            url = asyncio.get_running_loop().create_future()
            reader = asyncio.create_task(read_tunnel_url(process, url))
            async with asyncio.timeout(30):
                origin = await asyncio.shield(url)
            if origin is None:
                raise RuntimeError("cloudflared exited before creating the Quick Tunnel")
            exited = asyncio.create_task(process.wait())
            yield origin + CALLBACK_PATH, exited
        finally:
            server.should_exit = True
            try:
                await asyncio.wait_for(serving, timeout=5)
            finally:
                if process is not None and process.returncode is None:
                    try:
                        process.terminate()
                    except ProcessLookupError:
                        pass
                if process:
                    try:
                        await asyncio.wait_for(process.wait(), timeout=5)
                    except TimeoutError:
                        process.kill()
                        await process.wait()
                if reader:
                    await asyncio.gather(reader, return_exceptions=True)
                if exited:
                    await asyncio.gather(exited, return_exceptions=True)


class CallbackServer(uvicorn.Server):
    def capture_signals(self):
        # The main MCP listener owns Ctrl+C and shutdown.
        return nullcontext()


async def read_tunnel_url(process, url):
    origin = None
    connected = False
    while line := await process.stdout.readline():
        match = TUNNEL_URL.search(line)
        if match:
            origin = match[0].decode("ascii")
        if b"Registered tunnel connection" in line:
            connected = True
        if origin and connected and not url.done():
            url.set_result(origin)
    if not url.done():
        # Wake the startup waiter without logging subprocess output.
        url.set_result(None)
