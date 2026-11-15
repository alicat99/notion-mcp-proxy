"""Notion OAuth provider and credential storage."""

import json
import time

import keyring
from mcp.client.auth import OAuthClientProvider
from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata, OAuthToken


def create_oauth(server_url, storage, redirect_uri, redirect_handler, callback_handler):
    provider = OAuthClientProvider(
        server_url=server_url,
        client_metadata=OAuthClientMetadata(
            client_name="Notion MCP Proxy",
            redirect_uris=[redirect_uri],
            token_endpoint_auth_method="none",
        ),
        storage=storage,
        redirect_handler=redirect_handler,
        callback_handler=callback_handler,
    )
    provider.context.token_expiry_time = storage.expires_at
    return provider


class KeyringStorage:
    def __init__(self, server_url, *, fresh=False):
        self.service = f"notion-proxy-playground:{server_url}"
        self.tokens = None
        self.client_info = None
        self.expires_at = None
        self.slot = keyring.get_password(self.service, "credentials_slot")
        if fresh:
            return
        if self.slot:
            data = json.loads(keyring.get_password(self.service, f"tokens_{self.slot}"))
            self.tokens = OAuthToken.model_validate(data["tokens"])
            registration = keyring.get_password(self.service, f"client_info_{self.slot}")
            self.client_info = OAuthClientInformationFull.model_validate_json(registration)
            self.expires_at = data["expires_at"]
        else:
            tokens = keyring.get_password(self.service, "tokens")
            client_info = keyring.get_password(self.service, "client_info")
            if tokens and client_info:
                self.tokens = OAuthToken.model_validate_json(tokens)
                self.client_info = OAuthClientInformationFull.model_validate_json(client_info)
                # Legacy storage has no issue time. Refresh before guessing its expiry.
                self.expires_at = 1.0 if self.tokens.refresh_token else None

    async def get_tokens(self):
        return self.tokens

    async def set_tokens(self, tokens):
        expires_at = time.time() + tokens.expires_in if tokens.expires_in is not None else None
        # Keep entries small for Windows Credential Manager. Stage a matching
        # token and registration before switching away from the saved pair.
        slot = "b" if self.slot == "a" else "a"
        keyring.set_password(self.service, f"client_info_{slot}", self.client_info.model_dump_json())
        keyring.set_password(self.service, f"tokens_{slot}", json.dumps({
            "tokens": tokens.model_dump(mode="json"),
            "expires_at": expires_at,
        }))
        keyring.set_password(self.service, "credentials_slot", slot)
        self.slot = slot
        self.tokens = tokens
        self.expires_at = expires_at

    async def get_client_info(self):
        return self.client_info

    async def set_client_info(self, client_info):
        # Publish the registration only once it has a matching token.
        self.client_info = client_info
