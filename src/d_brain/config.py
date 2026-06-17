"""Application configuration using Pydantic Settings."""

from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    telegram_bot_token: str = Field(description="Telegram Bot API token")
    deepgram_api_key: str = Field(description="Deepgram API key for transcription")
    vault_path: Path = Field(
        default=Path("./vault"),
        description="Path to Obsidian vault directory",
    )
    allowed_user_ids: list[int] = Field(
        default_factory=list,
        description="List of Telegram user IDs allowed to use the bot",
    )
    allow_all_users: bool = Field(
        default=False,
        description="Whether to allow access to all users (security risk!)",
    )

    # ── persistent tmux session ──────────────────────────────────────
    runtime_dir: Path = Field(
        default_factory=lambda: Path.home() / ".dbrain",
        description="Runtime dir for locks, pane.log, ready/inflight flags",
    )
    brain_session_name: str = Field(
        default="",
        description="tmux session name (empty → generated & persisted per install)",
    )
    claude_model: str = Field(
        default="",
        description="Model for the session (empty = Claude Code default)",
    )
    tz: str = Field(default="UTC", description="Timezone for timers/reports")

    # ── cron (scheduled jobs in the second brain session) ────────────
    cron_enabled: bool = Field(
        default=True,
        description="Run the in-bot cron ticker",
    )
    cron_tick_seconds: float = Field(
        default=60.0,
        description="Ticker interval; jobs.json is re-read every tick",
    )
    cron_job_timeout: float = Field(
        default=600.0,
        description="Per-job ask() timeout in the cron session",
    )
    cron_max_consecutive_errors: int = Field(
        default=3,
        description="Consecutive failures before a job is auto-disabled",
    )
    cron_retry_seconds: float = Field(
        default=300.0,
        description="Retry delay for a failed one-shot ('at') job",
    )

    @field_validator("runtime_dir", "vault_path", mode="after")
    @classmethod
    def _expand_user(cls, v: Path) -> Path:
        # pydantic-settings keeps "~" literal; the cron CLI expanduser-s —
        # expand here too or the bot and CLI split into different state dirs.
        # resolve() makes the path ABSOLUTE: the brain runs `cd vault && cat
        # deploy/brain-system.md`, and a relative vault_path would make that
        # cat (and --mcp-config) resolve against the wrong cwd → persona
        # silently not loaded. One root of absoluteness for all derived paths.
        return v.expanduser().resolve()

    @property
    def cron_dir(self) -> Path:
        """Cron state dir: jobs.json + the cron session's runtime files."""
        return self.runtime_dir / "cron"

    @property
    def admin_chat_id(self) -> int | None:
        """First allowed user — destination for health alerts / reports."""
        return self.allowed_user_ids[0] if self.allowed_user_ids else None

    @property
    def daily_path(self) -> Path:
        """Path to daily notes directory."""
        return self.vault_path / "daily"

    @property
    def attachments_path(self) -> Path:
        """Path to attachments directory."""
        return self.vault_path / "attachments"

    @property
    def thoughts_path(self) -> Path:
        """Path to thoughts directory."""
        return self.vault_path / "thoughts"


def get_settings() -> Settings:
    """Get application settings instance."""
    return Settings()
