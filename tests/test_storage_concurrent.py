"""Concurrent attachments with the same timestamp must not overwrite."""

import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from d_brain.services.storage import VaultStorage


class ConcurrentStorageTests(unittest.TestCase):
    def test_same_second_saves_reserve_distinct_files(self):
        with tempfile.TemporaryDirectory() as directory:
            storage = VaultStorage(Path(directory))
            timestamp = datetime(2026, 11, 15, 12, 0)
            barrier = threading.Barrier(12)

            # Force the old check-then-write path to see every name as free
            # simultaneously. The exclusive-create path does not call exists.
            def simultaneous_exists():
                barrier.wait(timeout=5)
                return False

            with patch.object(Path, "exists", side_effect=simultaneous_exists):
                with ThreadPoolExecutor(max_workers=12) as pool:
                    paths = list(pool.map(
                        lambda i: storage.save_attachment(
                            str(i).encode(), timestamp.date(), timestamp
                        ),
                        range(12),
                    ))
            self.assertEqual(len(set(paths)), 12)
            self.assertEqual(
                {(Path(directory) / path).read_bytes() for path in paths},
                {str(i).encode() for i in range(12)},
            )
