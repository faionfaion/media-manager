"""Audit logging with rotation.

Prevents disk exhaustion from unbounded log growth.
Rotates daily, keeps 30 days of history.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

AUDIT_DIR = Path(__file__).resolve().parent.parent.parent / "logs"
MAX_AUDIT_FILES = 30  # keep 30 days of audit logs
MAX_AUDIT_FILE_SIZE = 10 * 1024 * 1024  # 10 MB per file


def audit_log(action: str, user_id: int, chat_id: int, text: str, detail: str = "") -> None:
    """Write an audit entry to today's log file."""
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    log_file = AUDIT_DIR / f"audit_{today}.jsonl"

    # Size guard — don't write if file too large (DoS prevention)
    if log_file.exists() and log_file.stat().st_size > MAX_AUDIT_FILE_SIZE:
        logger.warning("Audit log %s exceeds size limit, skipping write", log_file.name)
        return

    entry = json.dumps({
        "ts": datetime.now(timezone.utc).isoformat(),
        "action": action,
        "user_id": user_id,
        "chat_id": chat_id,
        "text": text[:200],  # cap text length
        "detail": detail[:500],  # cap detail length
    }, ensure_ascii=False)

    try:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(entry + "\n")
    except OSError as e:
        logger.error("Audit write failed: %s", e)


def rotate_audit_logs() -> int:
    """Remove audit logs older than MAX_AUDIT_FILES days. Returns count removed."""
    if not AUDIT_DIR.exists():
        return 0

    audit_files = sorted(AUDIT_DIR.glob("audit_*.jsonl"), reverse=True)
    removed = 0

    for f in audit_files[MAX_AUDIT_FILES:]:
        try:
            f.unlink()
            removed += 1
        except OSError:
            pass

    if removed:
        logger.info("Rotated %d old audit log files", removed)
    return removed


def get_audit_stats() -> dict:
    """Return audit statistics for /security command."""
    if not AUDIT_DIR.exists():
        return {"total_entries": 0, "blocked": 0, "files": 0}

    total = 0
    blocked = 0
    files = list(AUDIT_DIR.glob("audit_*.jsonl"))

    for f in files:
        try:
            for line in f.read_text(encoding="utf-8").splitlines():
                total += 1
                if any(k in line for k in ('"injection_blocked"', '"unauthorized"', '"forwarded_blocked"', '"rate_limited"')):
                    blocked += 1
        except OSError:
            pass

    # Also count legacy audit.jsonl if exists
    legacy = AUDIT_DIR / "audit.jsonl"
    if legacy.exists():
        try:
            for line in legacy.read_text(encoding="utf-8").splitlines():
                total += 1
                if any(k in line for k in ('"injection_blocked"', '"unauthorized"', '"forwarded_blocked"')):
                    blocked += 1
        except OSError:
            pass

    return {"total_entries": total, "blocked": blocked, "files": len(files)}
