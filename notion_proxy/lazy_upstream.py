"""Open upstream sessions on demand and coordinate interactive authorization."""

import asyncio
import logging
import shutil

from .oauth import KeyringStorage, create_oauth
from .oauth_callback import OAuthCallback, quick_tunnel
from .upstream import connect_upstream


logger = logging.getLogger(__name__)


class AuthorizationRequired(Exception):
    pass


class LazyUpstream:
    def __init__(self, url):
        self.url = url
        self.lock = asyncio.Lock()
        self.attempt = None
        self.ready = None

    async def run(self, operation):
        async with self.lock:
            if self.attempt and not self.attempt.done():
                await self._approval_required()

            storage = KeyringStorage(self.url)
            if storage.tokens and storage.client_info:
                required = asyncio.Event()

                async def defer_approval(_url=None):
                    required.set()
                    await asyncio.Future()  # The waiting tool call cancels this SDK request.

                registered = storage.client_info.redirect_uris
                provider = create_oauth(
                    self.url, storage, str(registered[0]) if registered else "http://127.0.0.1/callback",
                    defer_approval, defer_approval,
                )
                async with asyncio.timeout(120):
                    done, result = await self._try_operation(provider, operation, required)
                    if done:
                        return result

            executable = shutil.which("cloudflared")
            if not executable:
                raise AuthorizationRequired("Notion authorization requires cloudflared. Install it on the proxy host and retry.")
            self.ready = asyncio.get_running_loop().create_future()
            self.attempt = asyncio.create_task(self._authorize(executable, self.ready))
            await self._approval_required()

    async def close(self):
        if self.attempt:
            self.attempt.cancel()
            await asyncio.gather(self.attempt, return_exceptions=True)

    async def _approval_required(self):
        url = await asyncio.shield(self.ready)
        if not url:
            raise AuthorizationRequired("Could not start Notion authorization. Check the proxy log and retry.")
        raise AuthorizationRequired(
            f"Notion authorization is required. Open this URL in your browser:\n{url}\n"
            "After approval, return to the MCP client and retry. The proxy does not queue or replay this call."
        )

    async def _try_operation(self, provider, operation, required):
        async def call():
            async with connect_upstream(self.url, auth=provider) as upstream:
                return await operation(upstream)

        task = asyncio.create_task(call())
        auth_needed = asyncio.create_task(required.wait())
        try:
            # The SDK can handle transport errors in a separate task. Observe its
            # redirect signal directly instead of waiting for the request timeout.
            await asyncio.wait((task, auth_needed), return_when=asyncio.FIRST_COMPLETED)
            if required.is_set():
                return False, None
            return True, task.result()
        finally:
            task.cancel()
            auth_needed.cancel()
            await asyncio.gather(task, auth_needed, return_exceptions=True)

    async def _authorize(self, executable, ready):
        callback = OAuthCallback(ready.set_result)
        try:
            async with quick_tunnel(callback, executable) as (redirect_uri, tunnel_exit):
                storage = KeyringStorage(self.url, fresh=True)
                provider = create_oauth(self.url, storage, redirect_uri, callback.redirect, callback.receive)
                connection = asyncio.create_task(self._authorize_connection(provider, callback))
                try:
                    await self._wait_for(ready, connection, tunnel_exit, 30)
                    if await self._wait_for(callback.code, connection, tunnel_exit, 300) is None:
                        raise RuntimeError("Notion authorization was declined")
                    await self._wait_for(connection, connection, tunnel_exit, 30)
                finally:
                    if not callback.finished.done():
                        callback.finished.set_result(False)
                    connection.cancel()
                    await asyncio.gather(connection, return_exceptions=True)
        except Exception as error:
            logger.warning("Notion authorization did not complete (%s).", type(error).__name__)
        finally:
            if not ready.done():
                ready.set_result(None)

    async def _wait_for(self, expected, connection, tunnel_exit, timeout):
        async with asyncio.timeout(timeout):
            await asyncio.wait({expected, connection, tunnel_exit}, return_when=asyncio.FIRST_COMPLETED)
            if expected.done():
                return expected.result()
            if connection.done():
                connection.result()
            raise RuntimeError("Notion authorization ended before the callback completed")

    async def _authorize_connection(self, provider, callback):
        async with connect_upstream(self.url, auth=provider):
            callback.finished.set_result(True)
