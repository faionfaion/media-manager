"""Shared utilities for media-manager."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path


def count_articles_today(content_dir: Path, today: str | None = None) -> int:
    """Count articles for today. Checks both filename prefix and frontmatter date."""
    if today is None:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    if not content_dir.exists():
        return 0

    count = 0
    for md in content_dir.glob("*.md"):
        try:
            if md.name.startswith(today):
                count += 1
            else:
                text = md.read_text(encoding="utf-8")[:500]
                if f'date: "{today}"' in text:
                    count += 1
        except OSError:
            pass
    return count


def is_article_today(md_path: Path, today: str) -> bool:
    """Check if a single article is from today."""
    if md_path.name.startswith(today):
        return True
    try:
        text = md_path.read_text(encoding="utf-8")[:500]
        return f'date: "{today}"' in text
    except OSError:
        return False
