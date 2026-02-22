import json
from types import SimpleNamespace

import httpx
import pytest

from channel.feishu.client import FeishuClient


@pytest.mark.asyncio
async def test_create_reaction_typing_payload() -> None:
    calls = {"reaction_body": None}

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/tenant_access_token/internal"):
            return httpx.Response(
                status_code=200,
                json={"code": 0, "tenant_access_token": "t-1", "expire": 7200},
            )

        if request.url.path.endswith("/messages/om_1/reactions"):
            calls["reaction_body"] = json.loads(request.content.decode("utf-8"))
            return httpx.Response(status_code=200, json={"code": 0, "data": {}})

        return httpx.Response(status_code=404, json={"code": 99999})

    settings = SimpleNamespace(
        feishu_api_base="https://open.feishu.cn",
        feishu_app_id="cli_xxx",
        feishu_app_secret="secret",
        feishu_tenant_token_url="https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
        feishu_reply_url_template="https://open.feishu.cn/open-apis/im/v1/messages/{message_id}/reply",
        feishu_reaction_url_template="https://open.feishu.cn/open-apis/im/v1/messages/{message_id}/reactions",
    )

    client = FeishuClient(settings=settings)
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=10.0)

    await client.create_reaction(message_id="om_1", emoji_type="Typing", trace_id="t1")
    await client.close()

    assert calls["reaction_body"] == {"reaction_type": {"emoji_type": "Typing"}}
