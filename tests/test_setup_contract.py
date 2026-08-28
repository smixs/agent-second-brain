"""Contract tests for the install/upgrade scripts.

setup.sh once generated the dead v2 layout (system-level d-brain-* units)
— a fresh install was broken. These pins keep the install path honest:
setup.sh = interactive questions only, upgrade.sh = the single source of
truth for services and health.
"""

from pathlib import Path

ROOT = Path(__file__).parent.parent
SETUP = (ROOT / "setup.sh").read_text(encoding="utf-8")
UPGRADE = (ROOT / "upgrade.sh").read_text(encoding="utf-8")


def test_setup_delegates_services_to_upgrade():
    assert "upgrade.sh" in SETUP


def test_setup_has_no_dead_v2_layout():
    assert "d-brain-" not in SETUP  # legacy unit names
    assert "/etc/systemd/system" not in SETUP  # v3 uses systemd --user


def test_setup_login_check_uses_json_not_prose():
    # `claude auth status | grep "Logged in"` broke when the CLI changed
    # its prose; the JSON field is the stable contract.
    assert "loggedIn" in SETUP


def test_setup_asks_timezone():
    assert "TZ=" in SETUP


def test_upgrade_installs_the_single_unit():
    """One always-on unit now: polling, cron and the watchdog are supervised
    tasks in one process. The upgrade must also retire the split units."""
    assert "brain.service" in UPGRADE
    assert "brain-daily.timer" in UPGRADE
    assert "dbrain-watchdog.service" in UPGRADE  # disabled on upgrade


def test_units_exist_and_always_restart():
    unit = (ROOT / "deploy" / "brain.service").read_text(encoding="utf-8")
    assert "Restart=always" in unit
    # Type=notify + WatchdogSec is the only thing that catches a FROZEN
    # event loop; the old Type=simple unit made the bot's watchdog pings
    # dead code.
    assert "Type=notify" in unit
    assert "WatchdogSec=" in unit
    assert "KillMode=process" in unit  # a restart must not kill the tmux brain
    assert (ROOT / "deploy" / "brain-daily.timer").exists()


def test_split_units_are_gone():
    for stale in (
        "dbrain-bot.service",
        "dbrain-watchdog.service",
        "dbrain-doctor.service",
        "dbrain-notify@.service",
    ):
        assert not (ROOT / "deploy" / stale).exists()


def test_legacy_mac_installer_is_gone():
    assert not (ROOT / "install.sh").exists()
