from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.logging import setup_logging
from channel.feishu.client import FeishuClient
from channel.feishu.handler import FeishuWebhookHandler
from core.codex.client import CodexClient
from core.session.deduplicator import MessageDeduplicator
from core.session.manager import SessionManager
from core.session.task_registry import ActiveTaskRegistry

settings = get_settings()
setup_logging(settings.log_level)
logger = logging.getLogger(__name__)

app = FastAPI(title="CodexClaw", version="0.1.0")

session_manager = SessionManager(max_history_rounds=settings.max_history_rounds)
deduplicator = MessageDeduplicator(ttl_seconds=settings.deduplicate_ttl_seconds)
task_registry = ActiveTaskRegistry()
codex_client = CodexClient(settings=settings)
feishu_client = FeishuClient(settings=settings)
feishu_handler = FeishuWebhookHandler(
    settings=settings,
    feishu_client=feishu_client,
    codex_client=codex_client,
    session_manager=session_manager,
    deduplicator=deduplicator,
    task_registry=task_registry,
)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/webhook/feishu")
async def feishu_webhook(request: Request) -> JSONResponse:
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


@app.on_event("shutdown")
async def shutdown_event() -> None:
    await feishu_client.close()
    await codex_client.close()
