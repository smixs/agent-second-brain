"""Claude processing service.

Migrated from spawning `claude --print -p` per call to driving a shared
persistent interactive ClaudeSession (tmux). This keeps usage on the
subscription after the 2026-06-15 Agent SDK billing change. The public
methods and their {report|error} return shape are unchanged so the bot
handlers don't need to change.
"""

import logging
from datetime import date
from pathlib import Path
from typing import Any

from d_brain.services.claude_session import DEFAULT_TIMEOUT, AskResult, ClaudeSession
from d_brain.services.session import SessionStore

logger = logging.getLogger(__name__)

# User-facing messages for non-ok session outcomes (Telegram HTML).
_STATUS_MESSAGES = {
    "rate_limited": "⏳ <b>Лимит подписки исчерпан.</b> Вернусь, когда он обновится.",
    "logged_out": (
        "🔑 <b>Сессии нужен повторный вход.</b> Админу: <code>dbrain login</code>."
    ),
    "timeout": "⌛ <b>Превышено время ожидания ответа.</b> Попробуйте ещё раз.",
    "error": "❌ <b>Ошибка сессии.</b> Попробуйте позже.",
}


class ClaudeProcessor:
    """Builds prompts and runs them through the shared ClaudeSession."""

    def __init__(
        self,
        vault_path: Path,
        todoist_api_key: str = "",
        session: ClaudeSession | None = None,
    ) -> None:
        self.vault_path = Path(vault_path)
        self.todoist_api_key = todoist_api_key
        self.session = session

    # ── result mapping ───────────────────────────────────────────────

    def _to_report(self, res: AskResult) -> dict[str, Any]:
        if res.ok:
            return {"report": res.reply or "", "processed_entries": 1}
        logger.error("session returned %s: %s", res.status, res.detail)
        return {
            "error": _STATUS_MESSAGES.get(res.status, res.detail or "session error"),
            "processed_entries": 0,
        }

    def _ask(self, prompt: str) -> dict[str, Any]:
        if self.session is None:
            return {"error": "session not configured", "processed_entries": 0}
        return self._to_report(self.session.ask(prompt, timeout=DEFAULT_TIMEOUT))

    # ── content helpers (unchanged) ──────────────────────────────────

    def _load_skill_content(self) -> str:
        skill_path = self.vault_path / ".claude/skills/dbrain-processor/SKILL.md"
        return skill_path.read_text() if skill_path.exists() else ""

    def _load_todoist_reference(self) -> str:
        ref_path = (
            self.vault_path / ".claude/skills/dbrain-processor/references/todoist.md"
        )
        return ref_path.read_text() if ref_path.exists() else ""

    def _get_session_context(self, user_id: int) -> str:
        if user_id == 0:
            return ""
        session = SessionStore(self.vault_path)
        today_entries = session.get_today(user_id)
        if not today_entries:
            return ""
        lines = ["=== TODAY'S SESSION ==="]
        for entry in today_entries[-10:]:
            ts = entry.get("ts", "")[11:16]
            entry_type = entry.get("type", "unknown")
            text = entry.get("text", "")[:80]
            if text:
                lines.append(f"{ts} [{entry_type}] {text}")
        lines.append("=== END SESSION ===\n")
        return "\n".join(lines)

    def _html_to_markdown(self, html: str) -> str:
        import re

        text = html
        text = re.sub(r"<b>(.*?)</b>", r"**\1**", text)
        text = re.sub(r"<i>(.*?)</i>", r"*\1*", text)
        text = re.sub(r"<code>(.*?)</code>", r"`\1`", text)
        text = re.sub(r"<s>(.*?)</s>", r"~~\1~~", text)
        text = re.sub(r"</?u>", "", text)
        text = re.sub(r'<a href="([^"]+)">([^<]+)</a>', r"[\2](\1)", text)
        return text

    def _save_weekly_summary(self, report_html: str, week_date: date) -> Path:
        year, week, _ = week_date.isocalendar()
        filename = f"{year}-W{week:02d}-summary.md"
        summary_path = self.vault_path / "summaries" / filename
        content = self._html_to_markdown(report_html)
        frontmatter = (
            f"---\ndate: {week_date.isoformat()}\n"
            f"type: weekly-summary\nweek: {year}-W{week:02d}\n---\n\n"
        )
        summary_path.write_text(frontmatter + content)
        logger.info("Weekly summary saved to %s", summary_path)
        return summary_path

    def _update_weekly_moc(self, summary_path: Path) -> None:
        moc_path = self.vault_path / "MOC" / "MOC-weekly.md"
        if moc_path.exists():
            content = moc_path.read_text()
            link = f"- [[summaries/{summary_path.name}|{summary_path.stem}]]"
            if summary_path.stem not in content:
                content = content.replace(
                    "## Previous Weeks\n", f"## Previous Weeks\n\n{link}\n"
                )
                moc_path.write_text(content)
                logger.info("Updated MOC-weekly.md with %s", summary_path.stem)

    # ── public operations ────────────────────────────────────────────

    def process_daily(self, day: date | None = None) -> dict[str, Any]:
        if day is None:
            day = date.today()
        daily_file = self.vault_path / "daily" / f"{day.isoformat()}.md"
        if not daily_file.exists():
            logger.warning("No daily file for %s", day)
            return {"error": f"No daily file for {day}", "processed_entries": 0}

        skill_content = self._load_skill_content()
        prompt = f"""Сегодня {day}. Выполни ежедневную обработку.

=== SKILL INSTRUCTIONS ===
{skill_content}
=== END SKILL ===

CRITICAL OUTPUT FORMAT:
- Return ONLY raw HTML for Telegram (parse_mode=HTML)
- NO markdown: no **, no ## , no ```, no tables
- Start directly with 📊 <b>Обработка за {day}</b>
- Allowed tags: <b>, <i>, <code>, <s>, <u>
- If entries already processed, return status report in same HTML format"""
        return self._ask(prompt)

    def execute_prompt(self, user_prompt: str, user_id: int = 0) -> dict[str, Any]:
        today = date.today()
        todoist_ref = self._load_todoist_reference()
        session_context = self._get_session_context(user_id)
        prompt = f"""Ты - персональный ассистент d-brain.

CONTEXT:
- Текущая дата: {today}
- Vault path: {self.vault_path}

{session_context}=== TODOIST REFERENCE ===
{todoist_ref}
=== END REFERENCE ===

USER REQUEST:
{user_prompt}

CRITICAL OUTPUT FORMAT:
- Return ONLY raw HTML for Telegram (parse_mode=HTML)
- NO markdown: no **, no ##, no ```, no tables, no -
- Start with emoji and <b>header</b>
- Allowed tags: <b>, <i>, <code>, <s>, <u>
- Be concise - Telegram has 4096 char limit

EXECUTION:
1. Analyze the request
2. Call MCP tools directly (mcp__todoist__*, read/write files)
3. Return HTML status report with results"""
        return self._ask(prompt)

    def generate_weekly(self) -> dict[str, Any]:
        today = date.today()
        prompt = f"""Сегодня {today}. Сгенерируй недельный дайджест.

WORKFLOW:
1. Собери данные за неделю (daily файлы в vault/daily/, completed tasks через MCP)
2. Проанализируй прогресс по целям (goals/3-weekly.md)
3. Определи победы и вызовы
4. Сгенерируй HTML отчёт

CRITICAL OUTPUT FORMAT:
- Return ONLY raw HTML for Telegram (parse_mode=HTML)
- NO markdown: no **, no ##, no ```, no tables
- Start with 📅 <b>Недельный дайджест</b>
- Allowed tags: <b>, <i>, <code>, <s>, <u>
- Be concise - Telegram has 4096 char limit"""
        result = self._ask(prompt)
        if "report" in result and result["report"]:
            try:
                summary_path = self._save_weekly_summary(result["report"], today)
                self._update_weekly_moc(summary_path)
            except Exception as e:  # noqa: BLE001
                logger.warning("Failed to save weekly summary: %s", e)
        return result
