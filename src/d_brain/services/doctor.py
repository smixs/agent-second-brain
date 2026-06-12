"""Daily self-diagnostic for the persistent Claude session.

The "Doctor" the user asked for: once a day it asks the live session a canary
question (the authoritative check that auth + model + plumbing all work — a
silently-expired login is invisible to `claude auth status`), runs a handful
of cheap local checks, and reports a single 🟢/🔴 message to Telegram.

Run by a systemd timer and as the final step of install (install success ==
first green).
"""

import logging
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

CANARY_TOKEN = "DBRAIN_OK"
CANARY_TIMEOUT = 120.0


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str = ""


@dataclass
class DoctorReport:
    ok: bool
    checks: list[CheckResult] = field(default_factory=list)

    def to_telegram(self) -> str:
        header = (
            "🟢 <b>Осмотр пройден</b>" if self.ok else "🔴 <b>Осмотр: есть проблемы</b>"
        )
        lines = [f"{'✅' if c.ok else '❌'} {c.name}: {c.detail}" for c in self.checks]
        return header + "\n" + "\n".join(lines)


class Doctor:
    def __init__(
        self,
        session: Any,
        *,
        checks: list[Callable[[], CheckResult]] | None = None,
        canary_token: str = CANARY_TOKEN,
    ) -> None:
        self.session = session
        self._checks = checks if checks is not None else []
        self._canary_token = canary_token

    def _canary(self) -> CheckResult:
        res = self.session.ask(
            f"Reply with exactly {self._canary_token} and nothing else.",
            timeout=CANARY_TIMEOUT,
            request_id="maint-doctor",
        )
        if res.status == "logged_out":
            return CheckResult("canary", False, "Claude разлогинился — нужен вход")
        if res.status == "rate_limited":
            return CheckResult("canary", False, "лимит подписки исчерпан")
        if res.ok and self._canary_token in (res.reply or ""):
            return CheckResult("canary", True, "сессия отвечает")
        return CheckResult("canary", False, res.detail or res.status)

    def run(self) -> DoctorReport:
        checks = [self._canary()]
        for check in self._checks:
            try:
                checks.append(check())
            except Exception as exc:  # noqa: BLE001 — a check must never crash the doctor
                checks.append(
                    CheckResult(getattr(check, "__name__", "check"), False, str(exc))
                )
        return DoctorReport(ok=all(c.ok for c in checks), checks=checks)


# ── built-in local checks (used by main(); injected/faked in tests) ──────


def check_disk(runtime_dir: Path, min_bytes: int = 500_000_000) -> CheckResult:
    free = shutil.disk_usage(runtime_dir).free
    gb = free / 1_000_000_000
    return CheckResult("disk", free >= min_bytes, f"{gb:.1f} GB свободно")


def check_claude_version(claude_bin: str | None = None) -> CheckResult:
    # Manual runs (ssh, cron) often lack ~/.local/bin in PATH — resolve the
    # binary the way the install lays it out instead of false-alarming.
    bin_ = (
        claude_bin
        or shutil.which("claude")
        or str(Path.home() / ".local" / "bin" / "claude")
    )
    try:
        out = subprocess.run(
            [bin_, "--version"], capture_output=True, text=True, timeout=15
        )
        return CheckResult("claude", out.returncode == 0, out.stdout.strip() or "ok")
    except (OSError, subprocess.SubprocessError) as exc:
        return CheckResult("claude", False, str(exc))


def check_env(settings: Any) -> CheckResult:
    missing = [
        k
        for k, v in {
            "TELEGRAM_BOT_TOKEN": settings.telegram_bot_token,
            "DEEPGRAM_API_KEY": settings.deepgram_api_key,
        }.items()
        if not v
    ]
    return CheckResult(
        "env", not missing, "все ключи на месте" if not missing else f"нет: {missing}"
    )


def run_cli(session: Any, *, checks: list, alert: Any) -> int:
    """Run the checks, deliver the report, map health to an exit code —
    upgrade.sh and the systemd OnFailure= hook key off that code."""
    report = Doctor(session, checks=checks).run()
    alert(report.to_telegram())
    logger.info("doctor: ok=%s", report.ok)
    return 0 if report.ok else 1


def main() -> None:  # pragma: no cover
    logging.basicConfig(level=logging.INFO)
    from d_brain.config import get_settings
    from d_brain.services.runtime import get_session
    from d_brain.services.watchdog import _telegram_alerter

    settings = get_settings()
    session = get_session(settings)
    checks = [
        lambda: check_disk(settings.runtime_dir),
        lambda: check_claude_version(),
        lambda: check_env(settings),
    ]
    raise SystemExit(
        run_cli(session, checks=checks, alert=_telegram_alerter(settings))
    )


if __name__ == "__main__":
    main()
