"""Tests for ClaudeProcessor after migration to ClaudeSession.

A FakeSession replaces the real tmux session; we assert the processor builds
a prompt, calls ask(), and maps AskResult into the {report|error} dict the
bot handlers already expect.
"""

from datetime import date

from d_brain.services.claude_session import AskResult
from d_brain.services.processor import ClaudeProcessor


class FakeSession:
    def __init__(self, result: AskResult) -> None:
        self.result = result
        self.prompts: list[str] = []

    def ask(self, prompt: str, *, timeout: float = 1200, request_id=None) -> AskResult:  # noqa: ANN001
        self.prompts.append(prompt)
        return self.result


def test_execute_prompt_returns_report_on_ok(tmp_path):
    sess = FakeSession(AskResult("ok", reply="<b>done</b>"))
    p = ClaudeProcessor(tmp_path, session=sess)
    r = p.execute_prompt("move overdue tasks", user_id=0)
    assert r["report"] == "<b>done</b>"
    assert r["processed_entries"] == 1
    assert sess.prompts and "move overdue tasks" in sess.prompts[0]


def test_execute_prompt_maps_rate_limited(tmp_path):
    sess = FakeSession(AskResult("rate_limited"))
    p = ClaudeProcessor(tmp_path, session=sess)
    r = p.execute_prompt("x")
    assert "error" in r and r["processed_entries"] == 0


def test_execute_prompt_maps_logged_out(tmp_path):
    sess = FakeSession(AskResult("logged_out"))
    p = ClaudeProcessor(tmp_path, session=sess)
    r = p.execute_prompt("x")
    assert "error" in r


def test_execute_prompt_maps_timeout(tmp_path):
    sess = FakeSession(AskResult("timeout", detail="no reply"))
    p = ClaudeProcessor(tmp_path, session=sess)
    r = p.execute_prompt("x")
    assert "error" in r


def test_process_daily_missing_file_does_not_call_session(tmp_path):
    sess = FakeSession(AskResult("ok", reply="x"))
    p = ClaudeProcessor(tmp_path, session=sess)
    r = p.process_daily(date(2026, 6, 7))
    assert "error" in r
    assert sess.prompts == []  # never reached the session


def test_process_daily_ok(tmp_path):
    (tmp_path / "daily").mkdir()
    (tmp_path / "daily" / "2026-06-07.md").write_text(
        "# 2026-06-07\n## 10:00 [text]\nbuy milk\n"
    )
    sess = FakeSession(AskResult("ok", reply="<b>processed</b>"))
    p = ClaudeProcessor(tmp_path, session=sess)
    r = p.process_daily(date(2026, 6, 7))
    assert r["report"] == "<b>processed</b>"
    assert sess.prompts


def test_generate_weekly_ok(tmp_path):
    (tmp_path / "summaries").mkdir()
    sess = FakeSession(AskResult("ok", reply="<b>weekly</b>"))
    p = ClaudeProcessor(tmp_path, session=sess)
    r = p.generate_weekly()
    assert r["report"] == "<b>weekly</b>"
    assert sess.prompts
