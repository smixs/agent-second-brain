#!/bin/bash
# Upgrade an existing agent-second-brain install (v1 / v2) to v3.0 — the
# persistent interactive-session architecture — in one command:
#
#   bash upgrade.sh
#
# Installs tmux + deps, pulls the new code, migrates systemd units from the old
# d-brain-* names to dbrain-* (interactive session, watchdog, doctor), and runs
# a first health check. Idempotent — safe to re-run.
set -euo pipefail

# Non-interactive SSH shells have a minimal PATH — make sure uv/claude/node
# (in ~/.local/bin and nvm) are found.
export PATH="$HOME/.local/bin:$HOME/.nvm/versions/node/$(ls "$HOME/.nvm/versions/node/" 2>/dev/null | tail -1)/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
RUNTIME_DIR="${DBRAIN_RUNTIME_DIR:-$HOME/.dbrain}"
USER_UNITS="$HOME/.config/systemd/user"

say() { echo -e "\n\033[1m== $* ==\033[0m"; }

say "1/8 System dependencies (tmux, zram)"
if command -v apt-get >/dev/null 2>&1; then
    sudo apt-get update -qq || true
    sudo apt-get install -y tmux zram-tools >/dev/null || echo "  (apt install skipped/failed — install tmux manually if missing)"
else
    command -v tmux >/dev/null || echo "  ⚠ tmux not found and no apt — install it manually."
fi

say "2/8 Pulling latest code"
git -C "$PROJECT_DIR" pull --ff-only || echo "  (git pull skipped — not a clean fast-forward)"

say "3/8 Python dependencies (uv sync)"
( cd "$PROJECT_DIR" && uv sync )

say "4/8 Runtime dir + project pointer"
mkdir -p "$RUNTIME_DIR"
echo "$PROJECT_DIR" > "$RUNTIME_DIR/project.path"

say "5/8 Installing dbrain CLI"
if sudo install -m 0755 "$PROJECT_DIR/bin/dbrain" /usr/local/bin/dbrain 2>/dev/null; then
    echo "  installed /usr/local/bin/dbrain"
else
    mkdir -p "$HOME/.local/bin"
    install -m 0755 "$PROJECT_DIR/bin/dbrain" "$HOME/.local/bin/dbrain"
    echo "  installed ~/.local/bin/dbrain (ensure it's on PATH)"
fi

say "6/8 Migrating systemd --user units (d-brain-* → dbrain-*)"
mkdir -p "$USER_UNITS"
# Stop/disable legacy units if present.
systemctl --user disable --now \
    d-brain-bot.service d-brain-process.timer d-brain-weekly.timer 2>/dev/null || true
rm -f "$USER_UNITS"/d-brain-*.service "$USER_UNITS"/d-brain-*.timer
# v3.0 migration: the weekly digest is removed — retire its units on upgrade.
systemctl --user disable --now dbrain-weekly.timer dbrain-weekly.service 2>/dev/null || true
rm -f "$USER_UNITS"/dbrain-weekly.service "$USER_UNITS"/dbrain-weekly.timer
# Install new units, pointing WorkingDirectory/ExecStart at the real path.
for f in "$PROJECT_DIR"/deploy/dbrain-*.service "$PROJECT_DIR"/deploy/dbrain-*.timer; do
    sed "s|%h/projects/dbrain|$PROJECT_DIR|g" "$f" > "$USER_UNITS/$(basename "$f")"
done
systemctl --user daemon-reload
loginctl enable-linger "$USER" 2>/dev/null || echo "  ⚠ could not enable linger (services won't start on boot without it)"
systemctl --user enable \
    dbrain-bot.service dbrain-watchdog.service \
    dbrain-process.timer dbrain-doctor.timer
# restart (not just enable --now): on a re-run the units may have changed, and
# enable --now won't re-apply a new unit to an already-running service.
# KillMode=process means restarting the bot/watchdog does NOT kill the brain.
systemctl --user restart dbrain-bot.service dbrain-watchdog.service
systemctl --user start dbrain-process.timer dbrain-doctor.timer

# Privacy repair for existing installs: the runtime dir holds the full pane
# transcript (pane.log) and cron prompts — owner-only, whatever umask
# originally created them. New code enforces this; fix what's already there.
if [ -d "$RUNTIME_DIR" ]; then
    chmod 700 "$RUNTIME_DIR"
    find "$RUNTIME_DIR" -type d -exec chmod 700 {} +
    find "$RUNTIME_DIR" -type f -exec chmod 600 {} +
fi

say "7/8 Guard: no claude -p in the hot path"
bash "$PROJECT_DIR/scripts/check-no-claude-p.sh"

say "8/8 First health check"
( cd "$PROJECT_DIR" && uv run python -m d_brain.services.doctor ) || \
    echo "  (doctor reported issues — run 'dbrain status' / 'dbrain logs')"

echo
echo "✅ Upgrade complete. Your bot now runs on the persistent interactive"
echo "   session (subscription billing). Check it: dbrain status"
