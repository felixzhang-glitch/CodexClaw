from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote, urlparse

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
FILE_URI_RE = re.compile(r"file://[^\s)>\]\"']+", re.IGNORECASE)
PLAIN_PATH_RE = re.compile(r"(?<![\w/])(?:/[^:\n\r\t]+?\.(?:png|jpe?g|gif|webp|bmp))", re.IGNORECASE)


def extract_local_image_paths(text: str) -> list[str]:
    seen: set[str] = set()
    paths: list[str] = []

    for match in FILE_URI_RE.findall(text):
        parsed = urlparse(match)
        path = unquote(parsed.path)
        if _is_supported_image_path(path) and path not in seen:
            seen.add(path)
            paths.append(path)

    text_without_file_uris = FILE_URI_RE.sub(" ", text)
    for match in PLAIN_PATH_RE.findall(text_without_file_uris):
        path = match.strip()
        if _is_supported_image_path(path) and path not in seen:
            seen.add(path)
            paths.append(path)

    return paths


def remove_local_image_references(text: str) -> str:
    cleaned = FILE_URI_RE.sub("", text)
    cleaned = PLAIN_PATH_RE.sub("", cleaned)
    lines: list[str] = []
    for line in cleaned.splitlines():
        stripped = line.strip()
        if not stripped:
            lines.append(line)
            continue
        lowered = stripped.lower()
        if lowered in {"generated image:", "saved to:", "saved image:"}:
            continue
        if lowered.startswith("└ saved to:") or lowered.startswith("saved to:"):
            continue
        lines.append(line.rstrip())
    return "\n".join(lines).strip()


def find_recent_generated_images(directory: str, since: float, until: float | None = None) -> list[str]:
    root = Path(directory).expanduser()
    if not root.is_dir():
        return []

    upper = until if until is not None else float("inf")
    candidates: list[tuple[float, str]] = []
    for suffix in IMAGE_SUFFIXES:
        for path in root.rglob(f"*{suffix}"):
            try:
                modified_at = path.stat().st_mtime
            except OSError:
                continue
            if since <= modified_at <= upper:
                candidates.append((modified_at, str(path)))

    candidates.sort()
    return [path for _, path in candidates]


def _is_supported_image_path(path: str) -> bool:
    candidate = Path(path)
    return candidate.suffix.lower() in IMAGE_SUFFIXES and candidate.is_file()
