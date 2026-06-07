# Agent Second Brain

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Stars](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fapi.github.com%2Frepos%2Fsmixs%2Fagent-second-brain&query=%24.stargazers_count&label=stars&logo=github&color=blue)](https://github.com/smixs/agent-second-brain/stargazers)
[![Forks](https://img.shields.io/github/forks/smixs/agent-second-brain?style=flat&logo=github)](https://github.com/smixs/agent-second-brain/forks)

<p align="center">
  <img alt="Agent Second Brain" src="https://github.com/user-attachments/assets/5b3611d9-11ba-40a1-92fc-8dc78d78d75b" />
</p>

**Send a voice note to Telegram. Get an organized knowledge base, completed tasks, and a daily report back.** That's it. That's the whole idea.

[🇷🇺 Читать на русском](README.ru.md)

---

## The problem

Every productivity system dies the same way. You set it up on a Sunday, use it for two weeks, then slowly stop because the overhead of maintaining it is more work than the work itself.

You have notes everywhere. Voice memos you never re-listen to. Ideas that disappear into chat history. Tasks you forget to write down. And even when you do capture something, it sits in a folder you'll never open again.

The real issue: organizing takes more effort than thinking. So the thinking never gets organized.

## What this actually does

You talk to a Telegram bot. Voice, text, photos, forwarded messages - whatever is natural. You don't think about categories, tags, or where things go.

The agent handles everything else:

- **Transcribes** your voice notes (Deepgram, takes seconds)
- **Classifies** each entry - task, idea, client note, goal update, random thought
- **Creates tasks** in Todoist with the right priority and due date
- **Saves everything** to an Obsidian vault with proper links and tags
- **Sends you a daily report** at 9pm - what happened, what got done, what's still hanging
- **Remembers what matters, forgets what doesn't** - memory fades over time like a real brain

The bot runs 24/7 on a $5 VPS. You don't maintain it. You just talk to it.

## Talk to it like a person

This isn't a button-pressing bot. You have a conversation.

> **You:** what did I write about the marketing project last week?
>
> **Bot:** *finds and shows relevant entries*
>
> **You:** turn the second idea into a task for Monday
>
> **Bot:** *creates the task in Todoist*
>
> **You:** actually make it high priority and add a subtask for the presentation
>
> **Bot:** *updates the task*

It has access to your entire vault, all your goals, and your Todoist. Ask it anything about your own notes, and it'll find the answer.

## Memory that works like memory

Most AI systems either remember everything forever (drowning you in noise) or forget everything between sessions.

Agent Second Brain uses the Ebbinghaus forgetting curve - the same model that describes how human memory works. Every piece of information starts strong and gradually fades unless you access it again.

Five tiers, from always-on to nearly forgotten:

| Tier | What happens |
|------|-------------|
| **Core** | Always in context. Your current projects, active clients, key goals. |
| **Active** | Checked regularly. Recent ideas, ongoing conversations. |
| **Warm** | Found when you search. Last month's notes, past decisions. |
| **Cold** | Only surfaces in deep searches. Old projects, archived plans. |
| **Archive** | Almost gone - but sometimes randomly recalled for creative connections. |

The archive tier is the interesting one. Occasionally, the agent pulls a random old memory and connects it to something current. Sometimes it's noise. Sometimes it's the best idea you forgot you had.

## Vault health - your notes maintain themselves

Over time, note systems rot. Links break. Files become orphans. Tags diverge. You end up with a graveyard of markdown files that nobody, including you, can navigate.

The vault-health system runs automatically:

- Scores your vault on a 100-point scale
- Finds orphan notes (no links in or out) and suggests connections
- Repairs broken wiki-links
- Generates Maps of Content (MOCs) for each domain
- Flags files missing descriptions

You don't run maintenance. The agent does.

## What you send, what happens

| You send | Agent does |
|----------|-----------|
| Voice note about a client call | Transcribes, creates CRM card, adds follow-up task |
| Quick text: "idea for the Q2 campaign" | Saves to ideas folder, links to related notes |
| Forwarded article from a chat | Saves with source, extracts key points |
| Photo of a whiteboard | Saves with AI-generated description |
| "Process" button | Runs the full pipeline right now |
| "What are my priorities this week?" | Reads your goals and Todoist, gives you a straight answer |

## How it works (for the curious)

The daily processing runs in three phases:

1. **Capture** - reads today's entries, classifies each one (task? idea? CRM update? goal progress?)
2. **Execute** - creates Todoist tasks, writes vault files, updates cards
3. **Reflect** - generates a summary report, updates long-term memory, sends it to Telegram

Each phase produces a clean JSON that the next phase picks up. If something breaks, you can see exactly where and why.

```
Telegram → Deepgram → Claude Code → Todoist + Obsidian vault → Telegram report
```

**Always-on, on your subscription.** The bot doesn't spawn a fresh `claude` for every message. It keeps one long-lived *interactive* Claude Code session alive in a tmux pane and types your prompts into it. That keeps it on your Claude subscription (interactive usage) instead of per-request API billing. A watchdog and a daily self-check keep that session healthy around the clock and restart it automatically if it ever wedges — so the bot just stays up.

## What it costs

| Service | Cost |
|---------|------|
| Claude Pro | $20/mo |
| VPS (any cheap one works) | ~$5/mo |
| Deepgram | Free tier ($200 credit) |
| Todoist | Free plan works |
| **Total** | **~$25/mo** |

$25/month for a personal assistant that organizes your life, never sleeps, and gets better the more you use it.

> **Why this matters (June 2026).** From June 15, 2026 Anthropic moves `claude -p` / headless runs onto a separate paid Agent SDK credit, billed per request. Agent Second Brain **v3.1** sidesteps that completely: it drives a persistent *interactive* session, which stays on your flat Pro/Max subscription. No per-request billing, no surprise invoice — the price above stays the price. (If you ever do want the API path, an opt-in `DBRAIN_MODE=router` escape hatch is built in.)

## Quick start

### 1. Fork this repo

Click **Fork** at the top of this page. Make it **private** - it will contain your personal data.

### 2. Clone it

```bash
git clone https://github.com/YOUR_USERNAME/agent-second-brain.git
cd agent-second-brain
```

### 3. Fill in your info

Open these files and replace the placeholders:

- `vault/goals/` - your vision, yearly goals, monthly priorities, weekly focus
- `vault/.claude/skills/dbrain-processor/references/about.md` - tell the agent about yourself
- `vault/.claude/skills/dbrain-processor/references/classification.md` - how you want entries sorted

### 4. Get four API keys

| What | Where | Time |
|------|-------|------|
| Telegram Bot Token | [@BotFather](https://t.me/BotFather) | 2 min |
| Your Telegram ID | [@userinfobot](https://t.me/userinfobot) | 30 sec |
| Deepgram API Key | [console.deepgram.com](https://console.deepgram.com/) | 3 min |
| Todoist API Token | Todoist → Settings → Integrations → Developer | 1 min |

### 5. Deploy

Follow the [VPS setup guide](docs/vps-setup.md), or run:

```bash
ssh root@YOUR_SERVER_IP
curl -fsSL https://raw.githubusercontent.com/YOUR_USERNAME/agent-second-brain/main/bootstrap.sh | bash
```

That's it. The bot starts, you send it a message, and the system is alive.

### Already running an older version?

Upgrading an existing v2 / v3.0 install to the persistent-session architecture is one idempotent command — it installs tmux, pulls the new code, migrates the systemd services, and runs a health check:

```bash
ssh your-server
cd agent-second-brain && bash upgrade.sh
```

---

## Vault structure

```
vault/
├── daily/              # Your daily entries (voice, text, photos)
├── goals/              # Vision → yearly → monthly → weekly
├── business/
│   ├── crm/            # Client cards
│   └── network/        # Professional contacts
├── projects/           # Client work, leads, pipeline
├── thoughts/
│   ├── ideas/          # Ideas and brainstorms
│   ├── learnings/      # Lessons learned
│   └── reflections/    # Personal reflections
├── MOC/                # Maps of Content (auto-generated)
└── MEMORY.md           # Agent's long-term memory
```

## Skills

The agent has five built-in skills:

| Skill | What it does |
|-------|-------------|
| **dbrain-processor** | Classifies entries, creates tasks, saves notes |
| **agent-memory** | Ebbinghaus decay engine - remembers, forgets, recalls |
| **vault-health** | Scores vault health, fixes links, generates MOCs |
| **graph-builder** | Maps relationships between notes, finds clusters |
| **todoist-ai** | Manages tasks, projects, priorities |

Want just the memory engine? See [agent-memory-skill](https://github.com/smixs/agent-memory-skill) - works standalone, no dependencies.

## Configuration

| File | What it controls |
|------|-----------------|
| `.env` | API tokens (copy from `.env.example`) |
| `.memory-config.json` | How fast memories decay, tier boundaries |
| `mcp-config.json` | External tool connections |
| `vault/.claude/CLAUDE.md` | Agent personality and rules |

All secrets stay in `.env`, which is gitignored. Don't commit tokens.

---

## Built by

[Serge Shima](https://shima.me) - 20 years in marketing (BBDO, Publicis), now running an AI creative agency in Central Asia and teaching businesses how to work with AI at [aimasters.me](https://aimasters.me).

This system runs my actual life. 1,100+ vault cards, 5 AI agents, daily reports. It started as a weekend project and became infrastructure.

## License

[MIT](LICENSE) - do whatever you want with it.
