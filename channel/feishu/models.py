from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class FeishuTextMessageEvent:
    event_id: str
    message_id: str
    chat_id: str
    user_id: str
    text: str
    chat_type: str


def is_url_verification(payload: dict[str, Any]) -> bool:
    return payload.get("type") == "url_verification" and "challenge" in payload


def extract_token(payload: dict[str, Any]) -> str:
    if payload.get("token"):
        return str(payload.get("token"))

    header = payload.get("header")
    if isinstance(header, dict) and header.get("token"):
        return str(header.get("token"))

    return ""


def parse_text_message_event(
    payload: dict[str, Any],
    bot_open_id: str = "",
    group_require_mention: bool = True,
) -> FeishuTextMessageEvent | None:
    header = payload.get("header") or {}
    if header.get("event_type") != "im.message.receive_v1":
        return None

    event = payload.get("event")
    if not isinstance(event, dict):
        return None

    message = event.get("message")
    if not isinstance(message, dict):
        return None

    if message.get("message_type") != "text":
        return None

    chat_type = str(message.get("chat_type", "")).strip()
    if chat_type not in {"p2p", "group", "chat"}:
        return None

    content_raw = message.get("content")
    if not isinstance(content_raw, str):
        return None

    try:
        content = json.loads(content_raw)
    except json.JSONDecodeError:
        return None

    text = str(content.get("text", "")).strip()
    if not text:
        return None

    if chat_type != "p2p":
        mention_keys = _matching_mention_keys(message=message, bot_open_id=bot_open_id)
        if group_require_mention and not mention_keys:
            return None
        text = _strip_mention_keys(text=text, mention_keys=mention_keys)
        if not text:
            return None

    sender = event.get("sender") or {}
    sender_id = sender.get("sender_id") or {}
    user_id = sender_id.get("open_id") or sender_id.get("user_id") or sender_id.get("union_id")
    if not user_id:
        return None

    message_id = str(message.get("message_id", "")).strip()
    chat_id = str(message.get("chat_id", "")).strip()
    event_id = str(header.get("event_id", "")).strip()

    if not message_id or not chat_id:
        return None

    return FeishuTextMessageEvent(
        event_id=event_id,
        message_id=message_id,
        chat_id=chat_id,
        user_id=str(user_id),
        text=text,
        chat_type=chat_type,
    )


def parse_text_message_event_object(
    data: Any,
    bot_open_id: str = "",
    group_require_mention: bool = True,
) -> FeishuTextMessageEvent | None:
    """Parse lark_oapi websocket event objects with the same rules as webhook JSON."""
    header = _get_field(data, "header")
    event_type = _get_field(header, "event_type")
    if event_type and event_type != "im.message.receive_v1":
        return None

    event = _get_field(data, "event")
    if event is None:
        return None

    message = _get_field(event, "message")
    if message is None:
        return None

    if _get_field(message, "message_type") != "text":
        return None

    chat_type = str(_get_field(message, "chat_type") or "").strip()
    if chat_type not in {"p2p", "group", "chat"}:
        return None

    content_raw = _get_field(message, "content")
    content = _parse_content(content_raw)
    if content is None:
        return None

    text = str(_get_field(content, "text") or "").strip()
    if not text:
        return None

    if chat_type != "p2p":
        mention_keys = _matching_mention_keys_object(message=message, bot_open_id=bot_open_id)
        if group_require_mention and not mention_keys:
            return None
        text = _strip_mention_keys(text=text, mention_keys=mention_keys)
        if not text:
            return None

    sender = _get_field(event, "sender")
    sender_id = _get_field(sender, "sender_id")
    user_id = (
        _get_field(sender_id, "open_id")
        or _get_field(sender_id, "user_id")
        or _get_field(sender_id, "union_id")
    )
    if not user_id:
        return None

    message_id = str(_get_field(message, "message_id") or "").strip()
    chat_id = str(_get_field(message, "chat_id") or "").strip()
    event_id = str(_get_field(header, "event_id") or "").strip()

    if not message_id or not chat_id:
        return None

    return FeishuTextMessageEvent(
        event_id=event_id,
        message_id=message_id,
        chat_id=chat_id,
        user_id=str(user_id),
        text=text,
        chat_type=chat_type,
    )


def _matching_mention_keys(message: dict[str, Any], bot_open_id: str = "") -> list[str]:
    mentions = message.get("mentions")
    if not isinstance(mentions, list):
        return []

    expected_open_id = bot_open_id.strip()
    keys: list[str] = []
    for mention in mentions:
        if not isinstance(mention, dict):
            continue
        key = str(mention.get("key", "")).strip()
        if not key:
            continue
        if not expected_open_id:
            keys.append(key)
            continue

        mention_id = mention.get("id")
        if not isinstance(mention_id, dict):
            continue
        mention_ids = {
            str(mention_id.get("open_id", "")).strip(),
            str(mention_id.get("user_id", "")).strip(),
            str(mention_id.get("union_id", "")).strip(),
        }
        if expected_open_id in mention_ids:
            keys.append(key)
    return keys


def _matching_mention_keys_object(message: Any, bot_open_id: str = "") -> list[str]:
    mentions = _get_field(message, "mentions")
    if not isinstance(mentions, list):
        return []

    expected_open_id = bot_open_id.strip()
    keys: list[str] = []
    for mention in mentions:
        key = str(_get_field(mention, "key") or "").strip()
        if not key:
            continue
        if not expected_open_id:
            keys.append(key)
            continue

        mention_id = _get_field(mention, "id")
        mention_ids = {
            str(_get_field(mention_id, "open_id") or "").strip(),
            str(_get_field(mention_id, "user_id") or "").strip(),
            str(_get_field(mention_id, "union_id") or "").strip(),
        }
        if expected_open_id in mention_ids:
            keys.append(key)
    return keys


def _strip_mention_keys(text: str, mention_keys: list[str]) -> str:
    cleaned = text
    for key in mention_keys:
        cleaned = cleaned.replace(key, " ")
    return " ".join(cleaned.strip().split())


def _get_field(value: Any, name: str) -> Any:
    if value is None:
        return None
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)


def _parse_content(content_raw: Any) -> Any | None:
    if isinstance(content_raw, dict):
        return content_raw
    if not isinstance(content_raw, str):
        return None
    try:
        return json.loads(content_raw)
    except json.JSONDecodeError:
        return None
