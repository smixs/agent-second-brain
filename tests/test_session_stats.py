"""Regression tests for session statistics without a bot or external services."""

import json
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from d_brain.services.session import SessionStore


class FixedDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        fixed = cls(2026, 11, 15, 12, 0, tzinfo=UTC)
        return fixed.astimezone(tz) if tz else fixed


class SessionStatsTests(unittest.TestCase):
    def test_counts_the_full_window_and_compares_timezones(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SessionStore(Path(directory))
            records = [
                {"ts": "2026-11-15T12:00:00+00:00", "type": "voice"}
                for _ in range(1100)
            ]
            records += [
                {"ts": "2026-11-08T13:00:00+02:00", "type": "old"},
                {"ts": "2026-11-08T11:00:00-02:00", "type": "new"},
                {"ts": "invalid", "type": "bad"},
            ]
            path = store._get_session_file(1)
            path.write_text("\n".join(json.dumps(item) for item in records) + "\n{broken\n")
            with patch("d_brain.services.session.datetime", FixedDateTime):
                self.assertEqual(store.get_stats(1), {"voice": 1100, "new": 1})

    def test_missing_session_is_empty(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(SessionStore(Path(directory)).get_stats(1), {})
