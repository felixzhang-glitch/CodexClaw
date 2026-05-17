from channel.feishu.models import parse_message_event, parse_text_message_event


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


def test_parse_message_event_image_success() -> None:
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
                "message_type": "image",
                "content": '{"image_key": "img_v2_123"}',
            },
        },
    }

    event = parse_message_event(payload)

    assert event is not None
    assert event.message_type == "image"
    assert event.image_key == "img_v2_123"
    assert event.text == "用户发送了一张图片。"


def test_parse_text_message_event_ignores_image() -> None:
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
                "message_type": "image",
                "content": '{"image_key": "img_v2_123"}',
            },
        },
    }

    assert parse_text_message_event(payload) is None


def test_parse_message_event_post_with_text_and_image() -> None:
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
                "message_type": "post",
                "content": (
                    '{"post":{"zh_cn":{"title":"","content":['
                    '[{"tag":"text","text":"记录午餐"}],'
                    '[{"tag":"img","image_key":"img_v2_a"}],'
                    '[{"tag":"text","text":"少油"}],'
                    '[{"tag":"img","image_key":"img_v2_b"}]'
                    ']}}}'
                ),
            },
        },
    }

    event = parse_message_event(payload)

    assert event is not None
    assert event.message_type == "post"
    assert event.text == "记录午餐 少油"
    assert event.image_key == "img_v2_a"
    assert event.image_keys == ("img_v2_a", "img_v2_b")
