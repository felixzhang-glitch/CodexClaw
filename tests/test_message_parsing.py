from types import SimpleNamespace

from channel.feishu.models import parse_text_message_event, parse_text_message_event_object


def test_parse_text_message_event_success() -> None:
    payload = {
        "header": {
            "event_id": "evt_1",
            "event_type": "im.message.receive_v1",
        },
        "event": {
            "sender": {"sender_id": {"open_id": "ou_123"}},
            "message": {
                "message_id": "om_123",
                "chat_id": "oc_123",
                "chat_type": "p2p",
                "message_type": "text",
                "content": '{"text": "hello"}',
            },
        },
    }

    event = parse_text_message_event(payload)

    assert event is not None
    assert event.message_id == "om_123"
    assert event.chat_id == "oc_123"
    assert event.user_id == "ou_123"
    assert event.text == "hello"
    assert event.chat_type == "p2p"


def test_parse_text_message_event_ignore_group_without_mention() -> None:
    payload = {
        "header": {
            "event_id": "evt_1",
            "event_type": "im.message.receive_v1",
        },
        "event": {
            "sender": {"sender_id": {"open_id": "ou_123"}},
            "message": {
                "message_id": "om_123",
                "chat_id": "oc_123",
                "chat_type": "group",
                "message_type": "text",
                "content": '{"text": "hello"}',
            },
        },
    }

    assert parse_text_message_event(payload) is None


def test_parse_text_message_event_group_mention_strips_bot_token() -> None:
    payload = {
        "header": {
            "event_id": "evt_1",
            "event_type": "im.message.receive_v1",
        },
        "event": {
            "sender": {"sender_id": {"open_id": "ou_123"}},
            "message": {
                "message_id": "om_123",
                "chat_id": "oc_123",
                "chat_type": "group",
                "message_type": "text",
                "content": '{"text": "@_user_1 /help"}',
                "mentions": [
                    {
                        "key": "@_user_1",
                        "id": {"open_id": "ou_bot"},
                        "name": "CodexClaw",
                    }
                ],
            },
        },
    }

    event = parse_text_message_event(payload, bot_open_id="ou_bot")

    assert event is not None
    assert event.chat_type == "group"
    assert event.text == "/help"


def test_parse_text_message_event_group_ignores_other_mention_when_bot_id_configured() -> None:
    payload = {
        "header": {
            "event_id": "evt_1",
            "event_type": "im.message.receive_v1",
        },
        "event": {
            "sender": {"sender_id": {"open_id": "ou_123"}},
            "message": {
                "message_id": "om_123",
                "chat_id": "oc_123",
                "chat_type": "group",
                "message_type": "text",
                "content": '{"text": "@_user_1 hello"}',
                "mentions": [
                    {
                        "key": "@_user_1",
                        "id": {"open_id": "ou_other"},
                        "name": "Other",
                    }
                ],
            },
        },
    }

    assert parse_text_message_event(payload, bot_open_id="ou_bot") is None


def test_parse_text_message_event_object_success() -> None:
    data = SimpleNamespace(
        header=SimpleNamespace(event_id="evt_1", event_type="im.message.receive_v1"),
        event=SimpleNamespace(
            sender=SimpleNamespace(sender_id=SimpleNamespace(open_id="ou_123")),
            message=SimpleNamespace(
                message_id="om_123",
                chat_id="oc_123",
                chat_type="p2p",
                message_type="text",
                content='{"text": "/help"}',
            ),
        ),
    )

    event = parse_text_message_event_object(data)

    assert event is not None
    assert event.message_id == "om_123"
    assert event.chat_id == "oc_123"
    assert event.user_id == "ou_123"
    assert event.text == "/help"


def test_parse_text_message_event_object_group_mention_strips_bot_token() -> None:
    data = SimpleNamespace(
        header=SimpleNamespace(event_id="evt_1", event_type="im.message.receive_v1"),
        event=SimpleNamespace(
            sender=SimpleNamespace(sender_id=SimpleNamespace(open_id="ou_123")),
            message=SimpleNamespace(
                message_id="om_123",
                chat_id="oc_123",
                chat_type="group",
                message_type="text",
                content='{"text": "@_user_1 /help"}',
                mentions=[
                    SimpleNamespace(
                        key="@_user_1",
                        id=SimpleNamespace(open_id="ou_bot"),
                        name="CodexClaw",
                    )
                ],
            ),
        ),
    )

    event = parse_text_message_event_object(data, bot_open_id="ou_bot")

    assert event is not None
    assert event.text == "/help"
