"""Cron runner: the in-bot ticker that fires scheduled jobs in the cron
brain (the second, isolated ClaudeSession).

Semantics:
* jobs.json is re-read every tick (hot-reload — the brain edits it via
  the CLI while the bot runs).
* At-most-once: next_run is advanced and persisted BEFORE ask(), so a
  crash mid-run never refires the same slot.
* Self-healing lives here, not in the watchdog: a failed ask() recovers
  the cron session; max_consecutive_errors auto-disables the job and
  alerts the admin. rate_limited is not the job's fault — skip, wait.
* A reply starting with [SILENT] is not delivered (anti-spam for
  monitoring jobs).
"""

import asyncio
import contextlib
import copy
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from d_brain.services.cron_store import CronJob, CronStore, compute_next_run

logger = logging.getLogger(__name__)

SILENT_MARKER = "[SILENT]"


def wrap_job_prompt(job_id: str, prompt: str, *, scheduled_for: str | None) -> str:
    """Per-run envelope for the cron brain. The marker instruction is NOT
    duplicated here — ask(wrap=True) appends it."""
    return (
        f"[CRON JOB {job_id}] Это плановый запуск по расписанию "
        f"(scheduled_for: {scheduled_for}), не сообщение пользователя.\n\n"
        f"{prompt}\n\n"
        "Правила запуска: ответ уйдёт в Telegram — форматируй в HTML "
        "(<b> <i> <code> <a>), без Markdown. Если доставлять нечего — начни "
        f"ответ строкой {SILENT_MARKER}. В этом запуске ЗАПРЕЩЕНО создавать, "
        "изменять или удалять cron-задания (никаких d_brain.cron add/remove)."
    )


def _find(jobs: list[CronJob], job_id: str) -> CronJob | None:
    return next((j for j in jobs if j.id == job_id), None)


class CronRunner:
    def __init__(
        self,
        store: CronStore,
        session: Any,
        *,
        deliver: Callable[[int, str], Awaitable[None]],
        alert: Callable[[str], Awaitable[None]],
        default_chat_id: int | None,
        job_timeout: float = 600.0,
        max_consecutive_errors: int = 3,
        retry_seconds: float = 300.0,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.store = store
        self.session = session
        self.deliver = deliver
        self.alert = alert
        self.default_chat_id = default_chat_id
        self.job_timeout = job_timeout
        self.max_consecutive_errors = max_consecutive_errors
        self.retry_seconds = retry_seconds
        self.clock = clock or (lambda: datetime.now(UTC))

    # ── scheduling ───────────────────────────────────────────────────

    def claim_due(self, now: datetime) -> list[CronJob]:
        """Snapshot due jobs and advance their next_run under the lock.

        Persisting the advance BEFORE execution gives at-most-once: a
        crash mid-ask never refires the slot. One-shot ('at') jobs are
        re-armed to now+retry (not None) — so a crash between claim and
        record leaves a job that fires again instead of a bricked one;
        success then deletes it or clears next_run.
        """
        claimed: list[CronJob] = []

        def advance(jobs: list[CronJob]) -> None:
            for job in jobs:
                if not job.enabled or not job.state.next_run:
                    continue
                try:
                    due_at = datetime.fromisoformat(job.state.next_run)
                except ValueError:
                    # One malformed entry must not stall the whole schedule.
                    logger.error(
                        "job %s has malformed next_run %r — skipping",
                        job.id,
                        job.state.next_run,
                    )
                    continue
                if due_at.tzinfo is None:
                    due_at = due_at.replace(tzinfo=UTC)
                if due_at > now:
                    continue
                claimed.append(copy.deepcopy(job))
                if job.schedule.kind == "at":
                    retry_at = now + timedelta(seconds=self.retry_seconds)
                    job.state.next_run = retry_at.isoformat()
                else:
                    nxt = compute_next_run(job.schedule, now=now)
                    job.state.next_run = nxt.isoformat() if nxt else None

        self.store.mutate(advance)
        return claimed

    # ── execution ────────────────────────────────────────────────────

    async def run_job(self, job: CronJob) -> None:
        wrapped = wrap_job_prompt(
            job.id, job.prompt, scheduled_for=job.state.next_run
        )
        res = await asyncio.to_thread(
            self.session.ask, wrapped, timeout=self.job_timeout
        )
        now = self.clock()

        if res.status == "rate_limited":
            logger.warning("cron job %s skipped: subscription rate limit", job.id)
            self._record_failure(job, now, status="rate_limited", count=False)
            return

        if res.ok:
            reply = (res.reply or "").strip()
            silent = reply.startswith(SILENT_MARKER)
            delivery_error: str | None = None
            if reply and not silent:
                chat = job.chat_id or self.default_chat_id
                if chat is not None:
                    try:
                        await self.deliver(chat, reply)
                    except Exception as exc:  # noqa: BLE001 — Telegram hiccup
                        logger.exception("cron job %s delivery failed", job.id)
                        delivery_error = str(exc)[:200]
            # Jobs are stateless by contract; drop the turn's context so
            # the next job starts clean and the window never grows. Best
            # effort — a failed /clear must not block the state update.
            with contextlib.suppress(Exception):
                await asyncio.to_thread(self.session.send_control, "/clear")
            if delivery_error is not None:
                # The work happened but the user never saw it: keep the job
                # (one-shots retry) and count the failure.
                self._record_failure(
                    job, now, status="deliver_error", detail=delivery_error, count=True
                )
            else:
                self._record_success(job, now, silent=silent)
            return

        logger.error("cron job %s failed: %s %s", job.id, res.status, res.detail)
        await asyncio.to_thread(self.session.force_recover)
        disabled = self._record_failure(
            job, now, status=res.status, detail=res.detail, count=True
        )
        if disabled:
            await self.alert(
                f"⛔ Cron job <code>{job.id}</code> отключён после "
                f"{self.max_consecutive_errors} ошибок подряд "
                f"(последняя: {res.status}). Включить: "
                f"<code>python -m d_brain.cron enable {job.id}</code>"
            )

    # ── state updates (single write path: store.mutate) ─────────────

    def _record_success(self, job: CronJob, now: datetime, *, silent: bool) -> None:
        def fn(jobs: list[CronJob]) -> None:
            current = _find(jobs, job.id)
            if current is None:
                return
            if job.delete_after_run:
                jobs.remove(current)
                return
            current.state.last_run = now.isoformat()
            current.state.last_status = "ok-silent" if silent else "ok"
            current.state.last_error = None
            current.state.consecutive_errors = 0
            if current.schedule.kind == "at":
                # Claim re-armed a retry slot; the one-shot has now fired.
                current.state.next_run = None

        self.store.mutate(fn)

    def _record_failure(
        self,
        job: CronJob,
        now: datetime,
        *,
        status: str,
        detail: str | None = None,
        count: bool,
    ) -> bool:
        """Update job state after a non-ok run; True if it got disabled."""
        disabled = False

        def fn(jobs: list[CronJob]) -> None:
            nonlocal disabled
            current = _find(jobs, job.id)
            if current is None:
                return
            current.state.last_run = now.isoformat()
            current.state.last_status = status
            current.state.last_error = detail
            if count:
                current.state.consecutive_errors += 1
                if current.state.consecutive_errors >= self.max_consecutive_errors:
                    current.enabled = False
                    disabled = True
            # A claimed one-shot lost its next_run; re-arm a retry unless
            # the job just got disabled.
            if current.schedule.kind == "at" and not disabled:
                retry_at = now + timedelta(seconds=self.retry_seconds)
                current.state.next_run = retry_at.isoformat()

        self.store.mutate(fn)
        return disabled

    # ── loop ─────────────────────────────────────────────────────────

    async def tick(self) -> None:
        for job in self.claim_due(self.clock()):
            try:
                await self.run_job(job)
            except Exception as exc:  # noqa: BLE001 — one job must not kill the batch
                logger.exception("cron job %s crashed", job.id)
                with contextlib.suppress(Exception):
                    self._record_failure(
                        job,
                        self.clock(),
                        status="crash",
                        detail=str(exc)[:200],
                        count=True,
                    )

    async def run(self, tick_seconds: float) -> None:
        logger.info("cron runner started (tick %.0fs)", tick_seconds)
        while True:
            try:
                await self.tick()
            except Exception:  # noqa: BLE001 — one bad tick must not kill the loop
                logger.exception("cron tick failed")
            await asyncio.sleep(tick_seconds)


async def run_cron(settings: Any, bot: Any) -> None:
    """Wire the runner to the real store, cron session and Telegram."""
    from d_brain.bot.formatters import send_response
    from d_brain.services import runtime

    store = CronStore(settings.cron_dir)
    session = runtime.get_cron_session(settings)

    async def deliver(chat_id: int, text: str) -> None:
        await send_response(bot, chat_id, text)

    async def alert(text: str) -> None:
        if settings.admin_chat_id is not None:
            await bot.send_message(settings.admin_chat_id, text)

    runner = CronRunner(
        store,
        session,
        deliver=deliver,
        alert=alert,
        default_chat_id=settings.admin_chat_id,
        job_timeout=settings.cron_job_timeout,
        max_consecutive_errors=settings.cron_max_consecutive_errors,
        retry_seconds=settings.cron_retry_seconds,
    )
    await runner.run(settings.cron_tick_seconds)
