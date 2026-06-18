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
        feishu_send_message_url="https://open.feishu.cn/open-apis/im/v1/messages",
        feishu_image_upload_url="https://open.feishu.cn/open-apis/im/v1/images",
        feishu_reaction_url_template="https://open.feishu.cn/open-apis/im/v1/messages/{message_id}/reactions",
    )

    client = FeishuClient(settings=settings)
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=10.0)

    await client.create_reaction(message_id="om_1", emoji_type="Typing", trace_id="t1")
    await client.close()

    assert calls["reaction_body"] == {"reaction_type": {"emoji_type": "Typing"}}


@pytest.mark.asyncio
async def test_send_text_payload_to_chat_id() -> None:
    calls = {"send_body": None, "query": None}

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/tenant_access_token/internal"):
            return httpx.Response(
                status_code=200,
                json={"code": 0, "tenant_access_token": "t-1", "expire": 7200},
            )

        if request.url.path.endswith("/messages"):
            calls["send_body"] = json.loads(request.content.decode("utf-8"))
            calls["query"] = dict(request.url.params)
            return httpx.Response(status_code=200, json={"code": 0, "data": {"message_id": "om_new"}})

        return httpx.Response(status_code=404, json={"code": 99999})

    settings = SimpleNamespace(
        feishu_api_base="https://open.feishu.cn",
        feishu_app_id="cli_xxx",
        feishu_app_secret="secret",
        feishu_tenant_token_url="https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
        feishu_reply_url_template="https://open.feishu.cn/open-apis/im/v1/messages/{message_id}/reply",
        feishu_send_message_url="https://open.feishu.cn/open-apis/im/v1/messages",
        feishu_image_upload_url="https://open.feishu.cn/open-apis/im/v1/images",
        feishu_reaction_url_template="https://open.feishu.cn/open-apis/im/v1/messages/{message_id}/reactions",
    )

    client = FeishuClient(settings=settings)
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=10.0)

    message_id = await client.send_text(
        receive_id="oc_1",
        receive_id_type="chat_id",
        text="提醒内容",
        trace_id="t1",
        request_uuid="u1",
    )
    await client.close()

    assert message_id == "om_new"
    assert calls["query"] == {"receive_id_type": "chat_id"}
    assert calls["send_body"] == {
        "receive_id": "oc_1",
        "msg_type": "text",
        "content": '{"text": "提醒内容"}',
        "uuid": "u1",
    }


@pytest.mark.asyncio
async def test_send_markdown_payload_to_chat_id() -> None:
    calls = {"send_body": None, "query": None}

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/tenant_access_token/internal"):
            return httpx.Response(
                status_code=200,
                json={"code": 0, "tenant_access_token": "t-1", "expire": 7200},
            )

        if request.url.path.endswith("/messages"):
            calls["send_body"] = json.loads(request.content.decode("utf-8"))
            calls["query"] = dict(request.url.params)
            return httpx.Response(status_code=200, json={"code": 0, "data": {"message_id": "om_new"}})

        return httpx.Response(status_code=404, json={"code": 99999})

    settings = SimpleNamespace(
        feishu_api_base="https://open.feishu.cn",
        feishu_app_id="cli_xxx",
        feishu_app_secret="secret",
        feishu_tenant_token_url="https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
        feishu_reply_url_template="https://open.feishu.cn/open-apis/im/v1/messages/{message_id}/reply",
        feishu_send_message_url="https://open.feishu.cn/open-apis/im/v1/messages",
        feishu_image_upload_url="https://open.feishu.cn/open-apis/im/v1/images",
        feishu_reaction_url_template="https://open.feishu.cn/open-apis/im/v1/messages/{message_id}/reactions",
    )

    client = FeishuClient(settings=settings)
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=10.0)

    message_id = await client.send_markdown(
        receive_id="oc_1",
        receive_id_type="chat_id",
        markdown="**提醒内容**\n\n```python\nprint('ok')\n```",
        trace_id="t1",
        request_uuid="u1",
    )
    await client.close()

    assert message_id == "om_new"
    assert calls["query"] == {"receive_id_type": "chat_id"}
    assert calls["send_body"]["receive_id"] == "oc_1"
    assert calls["send_body"]["msg_type"] == "interactive"
    assert calls["send_body"]["uuid"] == "u1"
    card = json.loads(calls["send_body"]["content"])
    assert card["config"] == {"wide_screen_mode": True}
    assert card["elements"][0]["tag"] == "div"
    assert card["elements"][0]["text"] == {
        "tag": "lark_md",
        "content": "**提醒内容**\n\n```python\nprint('ok')\n```",
    }


@pytest.mark.asyncio
async def test_reply_markdown_payload() -> None:
    calls = {"reply_body": None}

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/tenant_access_token/internal"):
            return httpx.Response(
                status_code=200,
                json={"code": 0, "tenant_access_token": "t-1", "expire": 7200},
            )

        if request.url.path.endswith("/messages/om_1/reply"):
            calls["reply_body"] = json.loads(request.content.decode("utf-8"))
            return httpx.Response(status_code=200, json={"code": 0, "data": {}})

        return httpx.Response(status_code=404, json={"code": 99999})

    settings = SimpleNamespace(
        feishu_api_base="https://open.feishu.cn",
        feishu_app_id="cli_xxx",
        feishu_app_secret="secret",
        feishu_tenant_token_url="https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
        feishu_reply_url_template="https://open.feishu.cn/open-apis/im/v1/messages/{message_id}/reply",
        feishu_send_message_url="https://open.feishu.cn/open-apis/im/v1/messages",
        feishu_image_upload_url="https://open.feishu.cn/open-apis/im/v1/images",
        feishu_reaction_url_template="https://open.feishu.cn/open-apis/im/v1/messages/{message_id}/reactions",
    )

    client = FeishuClient(settings=settings)
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=10.0)

    await client.reply_markdown(message_id="om_1", markdown="# 标题", trace_id="t1", request_uuid="u1")
    await client.close()

    assert calls["reply_body"]["msg_type"] == "interactive"
    assert calls["reply_body"]["uuid"] == "u1"
    card = json.loads(calls["reply_body"]["content"])
    assert card["elements"][0]["text"] == {"tag": "lark_md", "content": "# 标题"}


@pytest.mark.asyncio
async def test_feishu_request_retries_transient_failure() -> None:
    calls = {"send": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/tenant_access_token/internal"):
            return httpx.Response(
                status_code=200,
                json={"code": 0, "tenant_access_token": "t-1", "expire": 7200},
            )

        if request.url.path.endswith("/messages"):
            calls["send"] += 1
            if calls["send"] == 1:
                return httpx.Response(status_code=500, json={"code": -1, "msg": "temporary"})
            return httpx.Response(status_code=200, json={"code": 0, "data": {"message_id": "om_new"}})

        return httpx.Response(status_code=404, json={"code": 99999})

    settings = SimpleNamespace(
        feishu_api_base="https://open.feishu.cn",
        feishu_app_id="cli_xxx",
        feishu_app_secret="secret",
        feishu_tenant_token_url="https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
        feishu_reply_url_template="https://open.feishu.cn/open-apis/im/v1/messages/{message_id}/reply",
        feishu_send_message_url="https://open.feishu.cn/open-apis/im/v1/messages",
        feishu_image_upload_url="https://open.feishu.cn/open-apis/im/v1/images",
        feishu_reaction_url_template="https://open.feishu.cn/open-apis/im/v1/messages/{message_id}/reactions",
        feishu_max_retries=1,
        feishu_retry_backoff_seconds=0,
    )

    client = FeishuClient(settings=settings)
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=10.0)

    message_id = await client.send_text(receive_id="oc_1", text="hello", trace_id="t1")
    await client.close()

    assert message_id == "om_new"
    assert calls["send"] == 2


@pytest.mark.asyncio
async def test_upload_image_payload(tmp_path) -> None:
    image_path = tmp_path / "image.png"
    image_path.write_bytes(b"fake image")
    calls = {"upload_body": b"", "content_type": ""}

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/tenant_access_token/internal"):
            return httpx.Response(
                status_code=200,
                json={"code": 0, "tenant_access_token": "t-1", "expire": 7200},
            )

        if request.url.path.endswith("/images"):
            calls["upload_body"] = request.content
            calls["content_type"] = request.headers.get("content-type", "")
            return httpx.Response(status_code=200, json={"code": 0, "data": {"image_key": "img_1"}})

        return httpx.Response(status_code=404, json={"code": 99999})

    settings = SimpleNamespace(
        feishu_api_base="https://open.feishu.cn",
        feishu_app_id="cli_xxx",
        feishu_app_secret="secret",
        feishu_tenant_token_url="https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
        feishu_reply_url_template="https://open.feishu.cn/open-apis/im/v1/messages/{message_id}/reply",
        feishu_send_message_url="https://open.feishu.cn/open-apis/im/v1/messages",
        feishu_image_upload_url="https://open.feishu.cn/open-apis/im/v1/images",
        feishu_reaction_url_template="https://open.feishu.cn/open-apis/im/v1/messages/{message_id}/reactions",
        feishu_max_retries=0,
        feishu_retry_backoff_seconds=0,
    )

    client = FeishuClient(settings=settings)
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=10.0)

    image_key = await client.upload_image(image_path=str(image_path), trace_id="t1")
    await client.close()

    assert image_key == "img_1"
    assert "multipart/form-data" in calls["content_type"]
    assert b'image_type' in calls["upload_body"]
    assert b"message" in calls["upload_body"]
    assert b"fake image" in calls["upload_body"]
