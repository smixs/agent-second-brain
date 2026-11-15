"""Vault storage service for saving entries."""

from datetime import date, datetime
from pathlib import Path


class VaultStorage:
    """Service for storing entries in Obsidian vault."""

    def __init__(self, vault_path: Path) -> None:
        self.vault_path = Path(vault_path)
        self.daily_path = self.vault_path / "daily"
        self.attachments_path = self.vault_path / "attachments"

    def _ensure_dirs(self) -> None:
        """Ensure required directories exist."""
        self.daily_path.mkdir(parents=True, exist_ok=True)
        self.attachments_path.mkdir(parents=True, exist_ok=True)

    def get_daily_file(self, day: date) -> Path:
        """Get path to daily file for given date."""
        self._ensure_dirs()
        return self.daily_path / f"{day.isoformat()}.md"

    def read_daily(self, day: date) -> str:
        """Read content of daily file."""
        file_path = self.get_daily_file(day)
        if not file_path.exists():
            return ""
        return file_path.read_text(encoding="utf-8")

    def append_to_daily(
        self,
        text: str,
        timestamp: datetime,
        msg_type: str,
    ) -> None:
        """Append entry to daily file.

        Args:
            text: Content to append
            timestamp: Entry timestamp
            msg_type: Type marker like [voice], [text], [photo], [forward from: Name]
        """
        self._ensure_dirs()
        file_path = self.get_daily_file(timestamp.date())

        time_str = timestamp.strftime("%H:%M")
        entry = f"\n## {time_str} {msg_type}\n{text}\n"

        with file_path.open("a", encoding="utf-8") as f:
            f.write(entry)

    def get_attachments_dir(self, day: date) -> Path:
        """Get attachments directory for given date."""
        dir_path = self.attachments_path / day.isoformat()
        dir_path.mkdir(parents=True, exist_ok=True)
        return dir_path

    def save_attachment(
        self,
        data: bytes,
        day: date,
        timestamp: datetime,
        extension: str = "jpg",
    ) -> str:
        """Save attachment and return relative path for Obsidian embed.

        Args:
            data: File bytes
            day: Date for organizing
            timestamp: Timestamp for filename
            extension: File extension

        Returns:
            Relative path for Obsidian embed: attachments/YYYY-MM-DD/img-HHMMSS.ext
        """
        dir_path = self.get_attachments_dir(day)
        time_str = timestamp.strftime("%H%M%S")
        # Telegram albums arrive as N messages within the same second —
        # uniquify so concurrent saves never overwrite each other.
        counter = 0
        while True:
            suffix = f"-{counter}" if counter else ""
            filename = f"img-{time_str}{suffix}.{extension}"
            try:
                # Exclusive creation reserves the name atomically across
                # concurrent handlers and processes.
                with (dir_path / filename).open("xb") as attachment:
                    attachment.write(data)
                break
            except FileExistsError:
                counter += 1

        return f"attachments/{day.isoformat()}/{filename}"
