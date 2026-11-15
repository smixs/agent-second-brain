"""Session history respects its limit, including zero and malformed lines."""

import tempfile
import unittest
from pathlib import Path

from d_brain.services.session import SessionStore


class SessionRecentTests(unittest.TestCase):
    def test_recent_limit_and_malformed_lines(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SessionStore(Path(directory))
            path = store._get_session_file(1)
            path.write_text('{"type":"one"}\n{bad\n{"type":"two"}\n{"type":"three"}\n')
            self.assertEqual([e["type"] for e in store.get_recent(1, limit=2)], ["two", "three"])
            self.assertEqual(len(store.get_recent(1, limit=10)), 3)
            self.assertEqual(store.get_recent(1, limit=0), [])
            self.assertEqual(store.get_recent(1, limit=-1), [])
            self.assertEqual(store.get_recent(2), [])
            store.append(2, "text", content="hello")
            self.assertEqual(store.get_recent(2, limit=1)[0]["content"], "hello")
