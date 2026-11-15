"""Session persistence service.

Stores all bot interactions in JSONL format for history and analytics.
Inspired by Clawdbot's session persistence pattern.
"""

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


class SessionStore:
    """Persistent session storage in JSONL format.

    Each user gets their own session file at vault/.sessions/{user_id}.jsonl.
    Entries are append-only for reliability and simplicity.
    """

    def __init__(self, vault_path: Path | str) -> None:
        self.sessions_dir = Path(vault_path) / ".sessions"
        self.sessions_dir.mkdir(exist_ok=True)

    def _get_session_file(self, user_id: int) -> Path:
        return self.sessions_dir / f"{user_id}.jsonl"

    def append(self, user_id: int, entry_type: str, **data: Any) -> None:
        """Append entry to user's session file.

        Args:
            user_id: Telegram user ID
            entry_type: Type of entry (voice, text, photo, forward, command, etc.)
            **data: Additional data to store (text, duration, msg_id, etc.)
        """
        entry = {
            "ts": datetime.now().astimezone().isoformat(),
            "type": entry_type,
            **data,
        }
        path = self._get_session_file(user_id)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def get_recent(self, user_id: int, limit: int = 50) -> list[dict]:
        """Get recent session entries.

        Args:
            user_id: Telegram user ID
            limit: Maximum number of entries to return

        Returns:
            List of session entries, most recent last
        """
        path = self._get_session_file(user_id)
        if not path.exists():
            return []

        entries = []
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue  # Skip malformed lines

        return entries[-limit:]

    def get_today(self, user_id: int) -> list[dict]:
        """Get today's session entries.

        Args:
            user_id: Telegram user ID

        Returns:
            List of today's entries
        """
        today = datetime.now().date().isoformat()
        return [
            e
            for e in self.get_recent(user_id, limit=200)
            if e.get("ts", "").startswith(today)
        ]

    def get_stats(self, user_id: int, days: int = 7) -> dict[str, int]:
        """Get usage statistics for the last N days.

        Args:
            user_id: Telegram user ID
            days: Number of days to analyze

        Returns:
            Dict with counts by entry type
        """
        cutoff = datetime.now().astimezone() - timedelta(days=days)
        stats: dict[str, int] = {}
        path = self._get_session_file(user_id)
        try:
            stream = path.open("r", encoding="utf-8")
        except FileNotFoundError:
            return stats
        with stream:
            for line in stream:
                try:
                    entry = json.loads(line)
                    timestamp = datetime.fromisoformat(entry["ts"])
                except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                    continue
                # Older entries without an offset are local, matching the
                # historical timestamp format used by this store.
                if timestamp.tzinfo is None:
                    timestamp = timestamp.astimezone()
                if timestamp < cutoff:
                    continue
                entry_type = entry.get("type", "unknown")
                stats[entry_type] = stats.get(entry_type, 0) + 1

        return stats
