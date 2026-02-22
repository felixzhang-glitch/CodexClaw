from channel.feishu.models import parse_text_message_event


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


def test_parse_text_message_event_ignore_non_p2p() -> None:
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
