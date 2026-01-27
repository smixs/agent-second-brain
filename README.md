# Agent Second Brain

Personal AI assistant with memory. Voice messages in Telegram get transcribed, saved to Obsidian, and create tasks in Todoist.

## Installation

```bash
curl -fsSL https://raw.githubusercontent.com/smixs/agent-second-brain/main/install.sh | bash
```

The script will install everything and prompt for your tokens.

**Works on:** Mac, Windows (WSL)

## Requirements

| Service | Purpose | Cost |
|---------|---------|------|
| Claude Pro | AI processing | $20/month |
| Telegram | Bot interface | Free |
| Deepgram | Voice transcription | Free ($200 credit) |
| Todoist | Task management | Free (optional) |

## What You Need Before Installing

1. **Claude Pro subscription** — [claude.ai/pricing](https://claude.ai/pricing)
2. **Telegram Bot Token** — create via [@BotFather](https://t.me/BotFather)
3. **Your Telegram ID** — get via [@userinfobot](https://t.me/userinfobot)
4. **Deepgram API Key** — [console.deepgram.com](https://console.deepgram.com/)
5. **Todoist API Token** (optional) — [Settings → Developer](https://todoist.com/app/settings/integrations/developer)

## Running the Bot

After installation:

```bash
cd ~/agent-second-brain && uv run python -m d_brain
```

Or if you configured autostart, it runs automatically.

## Features

| Feature | Description |
|---------|-------------|
| Voice messages | Transcribed via Deepgram Nova-3 |
| Text messages | Saved as-is |
| Photos | Saved with captions |
| Forwards | Saved with source attribution |
| Processing | Classifies entries, creates tasks, saves thoughts |
| Weekly digest | Analyzes your week, shows goal progress |
| Custom requests | "Move overdue tasks", "Show today's tasks" |

## Bot Commands

| Command | Action |
|---------|--------|
| `/start` | Start bot, show keyboard |
| `/help` | Show help |
| `/status` | How many entries today |
| `/process` | Process entries (create tasks, save thoughts) |
| `/weekly` | Generate weekly digest |
| `/do [text]` | Execute custom request |

## Vault Structure

```
vault/
├── daily/           # Daily entries (YYYY-MM-DD.md)
├── goals/           # Your goals (customize these!)
├── thoughts/        # Processed thoughts
│   ├── ideas/
│   ├── projects/
│   ├── learnings/
│   └── reflections/
├── summaries/       # Weekly digests
└── attachments/     # Photos by date
```

## Advanced

- [VPS Setup](docs/vps-setup.md) — Run 24/7 on a server
- [MCP CLI Setup](docs/mcp-cli-setup.md) — Todoist integration details

## Troubleshooting

### Bot doesn't respond

```bash
# Check if running
ps aux | grep d_brain

# Check logs (if autostart configured)
# Mac:
tail -f ~/agent-second-brain/logs/bot.log

# Linux/WSL:
journalctl --user -u agent-second-brain -f
```

### Voice not transcribing

Check your Deepgram key in `.env`:
```bash
cat ~/agent-second-brain/.env | grep DEEPGRAM
```

### Tasks not created

Check your Todoist token:
```bash
cat ~/agent-second-brain/.env | grep TODOIST
mcp-cli call todoist find-tasks-by-date '{"startDate": "today"}'
```

## License

MIT
