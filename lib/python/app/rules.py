"""Project-level rules loader.

Re-reads rule files on every call so edits take effect without restart.
rules/AGENTS.md is public; rules/admin.md holds private user info and is
gitignored. Long-term memory (memory/) is appended on top: opencode reads it
natively via the `instructions` config, the Claude-family backends get it
through this merged prompt block.
"""

from __future__ import annotations

import logging
import os

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
_RULES_DIR = os.path.join(_ROOT, "rules")
_RULE_FILES = ("AGENTS.md", "admin.md")

logger = logging.getLogger(__name__)


def load_system_rules() -> str:
    """Return rules/AGENTS.md + rules/admin.md merged with the memory block."""
    parts: list[str] = []
    for filename in _RULE_FILES:
        try:
            with open(os.path.join(_RULES_DIR, filename), encoding="utf-8") as f:
                content = f.read().strip()
        except OSError:
            continue
        if content:
            parts.append(content)

    memory_block = _load_memory_block()
    if memory_block:
        parts.append(memory_block)
    return "\n\n".join(parts)


def _load_memory_block() -> str:
    # Imported lazily to keep this module free of a config dependency at import
    # time, and guarded so memory problems can never block a reply.
    try:
        from app import memory

        memory.auto_commit()
        return memory.render_memory_block()
    except Exception:  # noqa: BLE001 - rules must stay loadable
        logger.warning("failed to load memory block", extra={"event": "memory.rules_inject"})
        return ""
