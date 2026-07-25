from __future__ import annotations

import asyncio
import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.logging import setup_logging
from channel.feishu.client import FeishuClient, FeishuClientError
from channel.feishu.handler import FeishuWebhookHandler
from channel.feishu.ws_client import FeishuWsClient
from channel.wechat.handler import WeChatWebhookHandler
from core.agent.router import AgentRouter
from core.session.deduplicator import MessageDeduplicator
from core.session.manager import SessionManager
from core.session.reminder_scheduler import ReminderScheduler
from core.session.task_registry import ActiveTaskRegistry

settings = get_settings()
setup_logging(settings.log_level)
logger = logging.getLogger(__name__)

app = FastAPI(title="codeClaw", version="0.1.0")

session_manager = SessionManager(max_history_rounds=settings.max_history_rounds)
deduplicator = MessageDeduplicator(ttl_seconds=settings.deduplicate_ttl_seconds)
task_registry = ActiveTaskRegistry()
codex_client = AgentRouter(settings=settings)
feishu_client = FeishuClient(settings=settings)


async def send_reminder(chat_id: str, text: str, trace_id: str) -> None:
    try:
        await feishu_client.send_markdown(
            receive_id=chat_id,
            receive_id_type="chat_id",
            markdown=text,
            trace_id=trace_id,
            request_uuid=trace_id,
        )
    except FeishuClientError:
        logger.warning("markdown reminder failed, falling back to text", extra={"trace_id": trace_id})
        await feishu_client.send_text(
            receive_id=chat_id,
            receive_id_type="chat_id",
            text=text,
            trace_id=trace_id,
            request_uuid=trace_id,
        )


reminder_scheduler = ReminderScheduler(callback=send_reminder, store_path=settings.reminder_store_path)
feishu_handler = FeishuWebhookHandler(
    settings=settings,
    feishu_client=feishu_client,
    codex_client=codex_client,
    session_manager=session_manager,
    deduplicator=deduplicator,
    task_registry=task_registry,
    reminder_scheduler=reminder_scheduler,
)
wechat_handler = WeChatWebhookHandler(
    settings=settings,
    codex_client=codex_client,
    session_manager=session_manager,
    deduplicator=deduplicator,
    task_registry=task_registry,
)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/webhook/feishu", deprecated=True)
async def feishu_webhook(request: Request) -> JSONResponse:
    """Legacy webhook endpoint. Use long-connection mode instead."""
    raw_body = await request.body()
    try:
        result = await feishu_handler.handle_webhook(headers=request.headers, raw_body=raw_body)
        return JSONResponse(content=result)
    except Exception as exc:
        status = getattr(exc, "status_code", 500)
        detail = getattr(exc, "detail", str(exc))
        if status >= 500:
            logger.exception("webhook failed")
        else:
            logger.warning("webhook rejected: %s", detail)
        return JSONResponse(status_code=status, content={"code": status, "msg": detail})


@app.post("/webhook/wechat")
async def wechat_webhook(request: Request) -> JSONResponse:
    raw_body = await request.body()
    try:
        result = await wechat_handler.handle_webhook(headers=request.headers, raw_body=raw_body)
        return JSONResponse(content=result)
    except Exception as exc:
        status = getattr(exc, "status_code", 500)
        detail = getattr(exc, "detail", str(exc))
        if status >= 500:
            logger.exception("wechat webhook failed")
        else:
            logger.warning("wechat webhook rejected: %s", detail)
        return JSONResponse(status_code=status, content={"code": status, "msg": detail})


@app.on_event("startup")
async def startup_event() -> None:
    await reminder_scheduler.start()
    loop = asyncio.get_running_loop()
    feishu_ws = FeishuWsClient(
        app_id=settings.feishu_app_id,
        app_secret=settings.feishu_app_secret,
        handler=feishu_handler,
        loop=loop,
        bot_open_id=settings.feishu_bot_open_id,
        group_require_mention=settings.feishu_group_require_mention,
    )
    feishu_ws.start_in_thread()


@app.on_event("shutdown")
async def shutdown_event() -> None:
    await reminder_scheduler.close()
    await feishu_client.close()
    await codex_client.close()
