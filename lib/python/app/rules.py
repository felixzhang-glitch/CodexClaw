"""Project-level rules loader.

Re-reads rule files on every call so edits take effect without restart.
rules/system.md is public; rules/admin.md holds private user info and is
gitignored.
"""

from __future__ import annotations

import os

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
_RULES_DIR = os.path.join(_ROOT, "rules")
_RULE_FILES = ("system.md", "admin.md")


def load_system_rules() -> str:
    """Return the merged content of rules/system.md and rules/admin.md."""
    parts: list[str] = []
    for filename in _RULE_FILES:
        try:
            with open(os.path.join(_RULES_DIR, filename), encoding="utf-8") as f:
                content = f.read().strip()
        except OSError:
            continue
        if content:
            parts.append(content)
    return "\n\n".join(parts)
