from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

import httpx

from app.config import Settings

logger = logging.getLogger(__name__)


class FeishuClientError(RuntimeError):
    pass


class FeishuClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = httpx.AsyncClient(timeout=20.0)
        self._token_lock = asyncio.Lock()
        self._tenant_access_token = ""
        self._token_expire_at = 0.0

    async def close(self) -> None:
        await self._client.aclose()

    async def reply_text(
        self,
        message_id: str,
        text: str,
        trace_id: str,
        request_uuid: str | None = None,
    ) -> None:
        if not text:
            return

        token = await self._get_tenant_access_token(trace_id=trace_id)
        url = self._settings.feishu_reply_url_template.format(message_id=message_id)

        payload: dict[str, Any] = {
            "msg_type": "text",
            "content": json.dumps({"text": text}, ensure_ascii=False),
        }
        if request_uuid:
            payload["uuid"] = request_uuid

        response = await self._client.post(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json=payload,
        )

        data = self._parse_response(response)
        if data.get("code") != 0:
            logger.error(
                "feishu reply failed",
                extra={
                    "trace_id": trace_id,
                    "event": "feishu.reply",
                    "status_code": response.status_code,
                    "error_code": data.get("code"),
                },
            )
            raise FeishuClientError(f"feishu reply failed: {data}")

        logger.info(
            "feishu reply sent",
            extra={
                "trace_id": trace_id,
                "event": "feishu.reply",
                "status_code": response.status_code,
            },
        )

    async def create_reaction(
        self,
        message_id: str,
        emoji_type: str,
        trace_id: str,
    ) -> None:
        token = await self._get_tenant_access_token(trace_id=trace_id)
        url = self._settings.feishu_reaction_url_template.format(message_id=message_id)

        response = await self._client.post(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json={
                "reaction_type": {
                    "emoji_type": emoji_type,
                }
            },
        )

        data = self._parse_response(response)
        if data.get("code") != 0:
            logger.error(
                "feishu reaction failed",
                extra={
                    "trace_id": trace_id,
                    "event": "feishu.reaction",
                    "status_code": response.status_code,
                    "error_code": data.get("code"),
                },
            )
            raise FeishuClientError(f"feishu reaction failed: {data}")

        logger.info(
            "feishu reaction sent",
            extra={
                "trace_id": trace_id,
                "event": "feishu.reaction",
                "status_code": response.status_code,
            },
        )

    async def _get_tenant_access_token(self, trace_id: str) -> str:
        now = time.time()
        if self._tenant_access_token and now < self._token_expire_at - 60:
            return self._tenant_access_token

        async with self._token_lock:
            now = time.time()
            if self._tenant_access_token and now < self._token_expire_at - 60:
                return self._tenant_access_token

            if not self._settings.feishu_app_id or not self._settings.feishu_app_secret:
                raise FeishuClientError("FEISHU_APP_ID / FEISHU_APP_SECRET is not configured")

            response = await self._client.post(
                self._settings.feishu_tenant_token_url,
                headers={"Content-Type": "application/json"},
                json={
                    "app_id": self._settings.feishu_app_id,
                    "app_secret": self._settings.feishu_app_secret,
                },
            )
            data = self._parse_response(response)
            if data.get("code") != 0:
                logger.error(
                    "failed to fetch feishu tenant token",
                    extra={
                        "trace_id": trace_id,
                        "event": "feishu.token",
                        "status_code": response.status_code,
                        "error_code": data.get("code"),
                    },
                )
                raise FeishuClientError(f"failed to fetch tenant access token: {data}")

            tenant_token = data.get("tenant_access_token", "")
            expires_in = int(data.get("expire", 7200))
            if not tenant_token:
                raise FeishuClientError("missing tenant_access_token in response")

            self._tenant_access_token = tenant_token
            self._token_expire_at = time.time() + expires_in

            logger.info(
                "feishu tenant token refreshed",
                extra={"trace_id": trace_id, "event": "feishu.token", "status_code": response.status_code},
            )

            return tenant_token

    @staticmethod
    def _parse_response(response: httpx.Response) -> dict[str, Any]:
        try:
            return response.json()
        except json.JSONDecodeError as exc:
            raise FeishuClientError(f"invalid feishu response status={response.status_code}") from exc
