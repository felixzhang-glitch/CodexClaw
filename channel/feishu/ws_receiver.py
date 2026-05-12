from __future__ import annotations

import asyncio
import logging
import threading
import uuid
from typing import Any

from channel.feishu.handler import FeishuWebhookHandler

logger = logging.getLogger(__name__)

try:
    import lark_oapi as lark
    import lark_oapi.ws.client as ws_client_module
    from lark_oapi.event.dispatcher_handler import EventDispatcherHandler
    from lark_oapi.ws import Client as FeishuWSClient
except Exception:  # pragma: no cover - exercised only when optional dependency is absent
    lark = None  # type: ignore[assignment]
    ws_client_module = None  # type: ignore[assignment]
    EventDispatcherHandler = None  # type: ignore[assignment]
    FeishuWSClient = None  # type: ignore[assignment]


class FeishuWebSocketReceiver:
    def __init__(self, settings: Any, handler: FeishuWebhookHandler) -> None:
        self._settings = settings
        self._handler = handler
        self._loop: asyncio.AbstractEventLoop | None = None
        self._future: asyncio.Future[Any] | None = None
        self._client: Any | None = None
        self._started = False

    @property
    def enabled(self) -> bool:
        return bool(getattr(self._settings, "feishu_ws_enabled", False))

    async def start(self) -> None:
        if self._started or not self.enabled:
            return
        if not self._settings.feishu_app_id or not self._settings.feishu_app_secret:
            logger.warning("feishu websocket disabled: missing app credentials")
            return
        if lark is None or EventDispatcherHandler is None or FeishuWSClient is None:
            logger.error("feishu websocket disabled: lark-oapi is not installed")
            return

        self._loop = asyncio.get_running_loop()
        event_handler = self._build_event_handler()
        self._client = FeishuWSClient(
            app_id=self._settings.feishu_app_id,
            app_secret=self._settings.feishu_app_secret,
            log_level=lark.LogLevel.WARNING,
            event_handler=event_handler,
            domain=self._settings.feishu_api_base.rstrip("/"),
        )
        self._future = self._loop.run_in_executor(None, self._run_client)
        self._started = True
        logger.info("feishu websocket receiver started")

    async def stop(self) -> None:
        client = self._client
        if client is not None:
            try:
                setattr(client, "_auto_reconnect", False)
            except Exception:
                logger.debug("failed to disable feishu websocket auto reconnect", exc_info=True)

        future = self._future
        if future is not None:
            future.cancel()
            try:
                await asyncio.wait_for(asyncio.shield(future), timeout=3.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
            except Exception:
                logger.debug("feishu websocket receiver stopped with error", exc_info=True)

        self._future = None
        self._client = None
        self._started = False

    def _build_event_handler(self) -> Any:
        return (
            EventDispatcherHandler.builder(
                self._settings.feishu_encrypt_key,
                self._settings.feishu_verification_token,
            )
            .register_p2_im_message_receive_v1(self._on_message_event)
            .build()
        )

    def _on_message_event(self, data: Any) -> None:
        loop = self._loop
        if loop is None or loop.is_closed():
            logger.warning("dropped feishu websocket event: app loop unavailable")
            return

        trace_id = uuid.uuid4().hex
        future = asyncio.run_coroutine_threadsafe(
            self._handler.handle_websocket_event(data=data, trace_id=trace_id),
            loop,
        )
        future.add_done_callback(self._log_background_failure)

    @staticmethod
    def _log_background_failure(future: Any) -> None:
        try:
            future.result()
        except Exception:
            logger.exception("feishu websocket event handling failed")

    def _run_client(self) -> None:
        client = self._client
        if client is None:
            return

        threading.current_thread().name = "feishu-ws-receiver"
        ws_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(ws_loop)
        if ws_client_module is not None:
            ws_client_module.loop = ws_loop
        try:
            client.start()
        except Exception:
            logger.exception("feishu websocket client exited with error")
        finally:
            pending = [task for task in asyncio.all_tasks(ws_loop) if not task.done()]
            for task in pending:
                task.cancel()
            if pending:
                ws_loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            ws_loop.close()
