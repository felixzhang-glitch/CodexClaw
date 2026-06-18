from channel.feishu.formatting import build_markdown_card, split_message_text


def test_split_message_text_prefers_paragraph_boundaries() -> None:
    chunks = split_message_text("第一段内容\n\n第二段内容\n\n第三段内容", max_chars=8)

    assert len(chunks) == 3
    assert chunks[0].startswith("(1/3)")
    assert "第一段内容" in chunks[0]
    assert "第二段内容" in chunks[1]


def test_split_message_text_preserves_small_code_block() -> None:
    text = "说明\n\n```python\nprint('hello')\n```\n\n结束"

    chunks = split_message_text(text, max_chars=60)

    assert chunks == [text]


def test_build_markdown_card_uses_lark_markdown_text() -> None:
    card = build_markdown_card("**重点**")

    assert card == {
        "config": {"wide_screen_mode": True},
        "elements": [
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": "**重点**",
                },
            }
        ],
    }
