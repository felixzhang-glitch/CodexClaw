"""Project-level rules loader.

Reads rules/system.md once at first access and caches the content for the
lifetime of the process.
"""

from __future__ import annotations

import os

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
_RULES_PATH = os.path.join(_ROOT, "rules", "system.md")
_rules_content: str | None = None


def load_system_rules() -> str:
    """Return the content of rules/system.md, cached after first read."""
    global _rules_content
    if _rules_content is None:
        try:
            with open(_RULES_PATH, encoding="utf-8") as f:
                _rules_content = f.read().strip()
        except FileNotFoundError:
            _rules_content = ""
    return _rules_content
