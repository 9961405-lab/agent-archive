from __future__ import annotations


def title_snippet(text: str) -> str:
    """First non-blank line, trimmed to 80 chars; '' if none."""
    for line in (text or "").splitlines():
        line = line.strip()
        if line:
            return line[:80]
    return ""
