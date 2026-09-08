import asyncio
import webbrowser
from urllib.parse import parse_qs, urlparse

import keyring
from mcp.client.auth import AuthorizationCodeResult, OAuthClientProvider
from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata, OAuthToken


def create_oauth(server_url):
    return OAuthClientProvider(
        server_url=server_url,
        client_metadata=OAuthClientMetadata(
            client_name="Notion Python playground",
            redirect_uris=["http://127.0.0.1:8765/callback"],
            token_endpoint_auth_method="none",
        ),
        storage=KeyringStorage(server_url),
        redirect_handler=open_browser,
        callback_handler=read_callback,
    )


async def open_browser(url):
    print("브라우저에서 승인한 뒤, 이동한 주소 전체를 아래에 붙여넣으세요.")
    print("콜백 서버를 실행하지 않으므로 브라우저의 연결 실패 화면은 정상입니다.")
    webbrowser.open(url)


async def read_callback():
    url = await asyncio.to_thread(input, "Callback URL: ")
    params = parse_qs(urlparse(url).query)
    if "error" in params:
        raise RuntimeError(f"OAuth authorization failed: {params['error'][0]}")
    return AuthorizationCodeResult(
        code=params["code"][0],
        state=params["state"][0],
        iss=params.get("iss", [None])[0],
    )


class KeyringStorage:
    def __init__(self, server_url):
        self.service = f"notion-proxy-playground:{server_url}"

    async def get_tokens(self):
        value = keyring.get_password(self.service, "tokens")
        return OAuthToken.model_validate_json(value) if value else None

    async def set_tokens(self, tokens):
        keyring.set_password(self.service, "tokens", tokens.model_dump_json())

    async def get_client_info(self):
        value = keyring.get_password(self.service, "client_info")
        return OAuthClientInformationFull.model_validate_json(value) if value else None

    async def set_client_info(self, client_info):
        keyring.set_password(self.service, "client_info", client_info.model_dump_json())
