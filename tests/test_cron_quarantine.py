"""A corrupt cron store is preserved even during repeated failures."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from d_brain.services.cron_store import CronStore


class CronQuarantineTests(unittest.TestCase):
    def test_repeated_corruption_in_one_second_preserves_both_files(self):
        with tempfile.TemporaryDirectory() as directory:
            store = CronStore(Path(directory))
            with patch("d_brain.services.cron_store.time.time", return_value=123):
                for contents in ("{first broken", "{second broken"):
                    store.jobs_file.write_text(contents)
                    self.assertEqual(store.load(), [])
            files = list(Path(directory).glob("jobs.json.corrupt-*"))
            self.assertEqual(len(files), 2)
            self.assertEqual({f.read_text() for f in files}, {"{first broken", "{second broken"})

    def test_valid_json_with_wrong_shape_is_quarantined(self):
        with tempfile.TemporaryDirectory() as directory:
            store = CronStore(Path(directory))
            for contents in ("[]", '{"jobs":[42]}', '{"jobs":[{"id":"x","prompt":"p","schedule":[1]}]}'):
                store.jobs_file.write_text(contents)
                self.assertEqual(store.load(), [])
            files = list(Path(directory).glob("jobs.json.corrupt-*"))
            self.assertEqual(len(files), 3)
