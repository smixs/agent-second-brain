---
name: migrate-doctor
description: Diagnose and repair a broken or non-standard agent-second-brain install/migration. Triggers — upgrade.sh failed, bot won't start after upgrade, "миграция сломалась", "бот не стартует после обновления", legacy d-brain units still present, brain session won't boot, doctor reports failures.
---

# Migrate Doctor

You are running INSIDE an interactive Claude Code session on the user's
server (subscription billing — this is the supported way to use AI for
repair). Your job: get a broken or half-migrated install to a healthy
v3.0 state. The deterministic path is `bash upgrade.sh` — your job is to
diagnose WHY it fails, remove the obstacle, and re-run it. Do not
re-implement the migration by hand unless upgrade.sh itself cannot work.

## Known version layouts

| Version | Markers | Notes |
|---|---|---|
| v1 (Dec 2025) | system-level `/etc/systemd/system/d-brain-bot.service`, `TODOIST_API_KEY` in .env, mcp-config.json | Todoist/MCP era, `claude -p` per message |
| v2 | `d-brain-*` units, `claude -p`/`claude --print` pipeline, weekly timer | headless calls — dead after 2026-06-15 billing change |
| v3.0 | `dbrain-*` systemd **--user** units (bot, watchdog, doctor, notify), persistent tmux brain, `~/.dbrain/` runtime dir | interactive session on subscription |
| v3.1 (target) | ONE `brain.service` --user unit (polling + cron + watchdog in one process) plus `brain-daily.timer` | same session, one process, rate limit with an expiry |

## Diagnosis checklist (read-only first)

```bash
# What's installed and running?
systemctl --user list-units 'brain*' 'dbrain-*' --all
sudo systemctl list-units 'd-brain-*' --all      # legacy system-level
ls ~/.dbrain/ 2>/dev/null                         # runtime dir (v3)
tmux ls 2>/dev/null                               # brain sessions
git -C ~/projects/agent-second-brain log --oneline -3
cat ~/projects/agent-second-brain/.env | grep -v 'TOKEN\|KEY'  # never print secrets
claude auth status --json                         # needs "loggedIn": true
journalctl --user -u brain.service -n 50 --no-pager
```

## Repair rules

1. **Backup before any destructive step**: `tar czf ~/dbrain-backup-$(date +%s).tgz -C ~/projects agent-second-brain --exclude=.venv` and note the current commit (`git rev-parse HEAD`).
2. **Never modify or delete vault content** (`vault/daily`, notes, cards). The vault is the user's data; migration touches code, units and runtime files only.
3. **Prefer re-running `bash upgrade.sh`** after each fix — it is idempotent. Fix the obstacle, not the symptom.
4. Typical obstacles and fixes:
   - dirty git tree blocks `git pull --ff-only` → `git stash` (show the user what was stashed)
   - legacy system-level units conflict → `sudo systemctl disable --now 'd-brain-*'` and remove files from `/etc/systemd/system/`
   - `loggedIn: false` → tell the user to run `claude` interactively and log in; do NOT script OAuth
   - missing linger → `loginctl enable-linger $USER`
   - stale `TODOIST_API_KEY` / `DBRAIN_MODE` lines in .env → remove them (v3 ignores but they confuse humans)
   - wedged brain session → `dbrain restart` or `tmux kill-session -t <brain>` (the bot recreates it lazily)
5. **Report honestly**: if a step failed, say so with the output. Never claim health you didn't verify.

## Verification (must pass before you declare success)

```bash
bash scripts/check-no-claude-p.sh                 # guard clean
systemctl --user is-active brain.service brain-daily.timer
uv run python -m d_brain.services.doctor          # ok=True
cat ~/.dbrain/STATUS.md                            # state: healthy
```

Finish with a short summary: what was broken, what you changed, what the
user should watch for. Suggest sending the bot a test voice message.
