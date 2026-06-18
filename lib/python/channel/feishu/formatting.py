from __future__ import annotations

import re
from typing import Any


def normalize_reply_text(text: str) -> str:
    cleaned = text.strip()
    if not cleaned:
        return ""
    cleaned = cleaned.replace("\r\n", "\n").replace("\r", "\n")
    cleaned = re.sub(r"\n{4,}", "\n\n\n", cleaned)
    return cleaned


def build_markdown_card(markdown: str) -> dict[str, Any]:
    return {
        "config": {"wide_screen_mode": True},
        "elements": [
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": markdown,
                },
            }
        ],
    }


def split_message_text(text: str, max_chars: int) -> list[str]:
    content = normalize_reply_text(text)
    if not content:
        return []

    limit = max(1, max_chars)
    if len(content) <= limit:
        return [content]

    chunks: list[str] = []
    current = ""
    for block in _iter_blocks(content):
        if not block:
            continue
        if len(block) > limit:
            if current:
                chunks.append(current.rstrip())
                current = ""
            chunks.extend(_split_large_block(block, limit))
            continue

        separator = "\n\n" if current else ""
        candidate = f"{current}{separator}{block}"
        if len(candidate) <= limit:
            current = candidate
        else:
            if current:
                chunks.append(current.rstrip())
            current = block

    if current:
        chunks.append(current.rstrip())

    if len(chunks) <= 1:
        return chunks
    total = len(chunks)
    return [f"({idx}/{total})\n{chunk}" for idx, chunk in enumerate(chunks, start=1)]


def _iter_blocks(text: str) -> list[str]:
    blocks: list[str] = []
    current: list[str] = []
    in_fence = False

    for line in text.splitlines():
        if line.strip().startswith("```"):
            in_fence = not in_fence
            current.append(line)
            continue

        if not in_fence and not line.strip():
            if current:
                blocks.append("\n".join(current).strip())
                current = []
            continue

        current.append(line)

    if current:
        blocks.append("\n".join(current).strip())
    return blocks


def _split_large_block(block: str, limit: int) -> list[str]:
    pieces: list[str] = []
    current = ""

    for line in block.splitlines():
        if len(line) > limit:
            if current:
                pieces.append(current.rstrip())
                current = ""
            pieces.extend(_split_by_sentence_or_hard(line, limit))
            continue

        candidate = f"{current}\n{line}" if current else line
        if len(candidate) <= limit:
            current = candidate
        else:
            if current:
                pieces.append(current.rstrip())
            current = line

    if current:
        pieces.append(current.rstrip())
    return pieces


def _split_by_sentence_or_hard(text: str, limit: int) -> list[str]:
    pieces: list[str] = []
    current = ""
    for part in re.split(r"([。！？.!?]\s*)", text):
        if not part:
            continue
        candidate = f"{current}{part}"
        if len(candidate) <= limit:
            current = candidate
            continue
        if current:
            pieces.append(current.strip())
        current = part
        while len(current) > limit:
            pieces.append(current[:limit].strip())
            current = current[limit:]

    if current.strip():
        pieces.append(current.strip())
    return pieces


def strip_markdown(text: str) -> str:
    """Convert markdown to readable plaintext for channels that don't render it."""
    if not text:
        return ""

    lines = text.splitlines()
    output: list[str] = []
    in_fence = False

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            output.append(line)
            continue
        line = re.sub(r"^(#{1,6})\s+", "", line)
        line = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", line)
        line = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 (\2)", line)
        line = re.sub(r"\*\*\*(.+?)\*\*\*", r"\1", line)
        line = re.sub(r"\*\*(.+?)\*\*", r"\1", line)
        line = re.sub(r"__(.+?)__", r"\1", line)
        line = re.sub(r"\*(.+?)\*", r"\1", line)
        line = re.sub(r"_(.+?)_", r"\1", line)
        line = re.sub(r"~~(.+?)~~", r"\1", line)
        line = re.sub(r"`([^`]+)`", r"\1", line)
        if re.match(r"^[-*_]{3,}\s*$", stripped):
            line = "---"
        output.append(line)

    return "\n".join(output)
