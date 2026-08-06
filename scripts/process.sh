#!/bin/bash
set -e

# PATH for systemd (claude, uv, npx, node)
export PATH="$HOME/.local/bin:$HOME/.nvm/versions/node/$(ls "$HOME/.nvm/versions/node/" 2>/dev/null | tail -1)/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

# Paths — auto-detect from script location
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VAULT_DIR="$PROJECT_DIR/vault"
ENV_FILE="$PROJECT_DIR/.env"

# Load environment variables (set -a survives quoted values and spaces,
# unlike export $(... | xargs), which word-splits and strips quotes)
if [ -f "$ENV_FILE" ]; then
    set -a
    # shellcheck disable=SC1090
    . "$ENV_FILE"
    set +a
fi

# Check token
if [ -z "$TELEGRAM_BOT_TOKEN" ]; then
    echo "ERROR: TELEGRAM_BOT_TOKEN not set"
    exit 1
fi

# Timezone (configure in .env: TZ=Your/Timezone)
export TZ="${TZ:-UTC}"

# Date and chat_id
TODAY=$(date +%Y-%m-%d)
CHAT_ID="${ALLOWED_USER_IDS//[\[\] ]/}"  # strip brackets/spaces from [123, 456]
CHAT_ID="${CHAT_ID%%,*}"  # first id only — the admin gets the report

echo "=== d-brain processing for $TODAY ==="

# ── ORIENT PHASE: pre-flight checks ──
DAILY_FILE="$VAULT_DIR/daily/$TODAY.md"
HANDOFF_FILE="$VAULT_DIR/.session/handoff.md"
GRAPH_FILE="$VAULT_DIR/.graph/vault-graph.json"

# Check daily file exists and has content
if [ ! -f "$DAILY_FILE" ]; then
    echo "ORIENT: daily/$TODAY.md not found — creating empty file"
    echo "# $TODAY" > "$DAILY_FILE"
fi

DAILY_SIZE=$(wc -c < "$DAILY_FILE" 2>/dev/null || echo "0")
if [ "$DAILY_SIZE" -lt 50 ]; then
    echo "ORIENT: daily/$TODAY.md is empty ($DAILY_SIZE bytes) — skipping Claude processing"
    echo "ORIENT: Running graph rebuild only"

    # Still rebuild graph and commit
    cd "$VAULT_DIR"
    uv run .claude/skills/autograph/scripts/graph.py health . || echo "Graph rebuild failed (non-critical)"
    cd "$PROJECT_DIR"

    git add -A
    git commit -m "chore: process daily $TODAY" || true
    git push || true
    echo "=== Done (empty daily, graph-only) ==="
    exit 0
fi

# Check handoff exists
if [ ! -f "$HANDOFF_FILE" ]; then
    echo "ORIENT: handoff.md not found — creating stub"
    mkdir -p "$VAULT_DIR/.session"
    echo -e "---\nupdated: $(date -Iseconds)\n---\n\n## Last Session\n(none)\n\n## Observations" > "$HANDOFF_FILE"
fi

# Check graph freshness (warn if >7 days old)
if [ -f "$GRAPH_FILE" ]; then
    GRAPH_AGE=$(( ($(date +%s) - $(stat -c %Y "$GRAPH_FILE" 2>/dev/null || stat -f %m "$GRAPH_FILE" 2>/dev/null || echo 0)) / 86400 ))
    if [ "$GRAPH_AGE" -gt 7 ]; then
        echo "ORIENT: vault-graph.json is $GRAPH_AGE days old (>7)"
    fi
fi

echo "ORIENT: daily=$DAILY_SIZE bytes, handoff=OK, graph=OK"
# ── END ORIENT PHASE ──

# ── Detect same-entity fact conflicts BEFORE processing, so the daily turn can
#    resolve them (rewrite current value + move old to ## History) ──
echo "=== Supersede scan (same-entity contradictions) ==="
cd "$VAULT_DIR"
uv run .claude/skills/autograph/scripts/supersede.py . || {
    echo "Supersede scan failed (non-critical) — clearing stale candidates"
    rm -f .graph/supersede-candidates.json
}
cd "$PROJECT_DIR"

# ── PROCESS via the persistent interactive session (NO claude -p) ──
# The 3-phase claude -p pipeline is gone: after 2026-06-15 that bills against
# the Agent SDK credit. We drive the long-lived interactive session instead,
# which stays on the subscription. The Python entrypoint runs the daily
# processing through the shared session and prints the HTML report.
echo "=== Daily processing (interactive session) ==="
REPORT=$(cd "$PROJECT_DIR" && uv run python -m d_brain.pipeline daily 2>&1) || true

echo "=== pipeline output ==="
echo "$REPORT"
echo "======================="

# Remove HTML comments (break Telegram HTML parser)
REPORT_CLEAN=$(echo "$REPORT" | sed '/<!--/,/-->/d')

# Rebuild vault graph (keeps structure up to date)
echo "=== Rebuilding vault graph ==="
cd "$VAULT_DIR"
uv run .claude/skills/autograph/scripts/graph.py health . || echo "Graph rebuild failed (non-critical)"

# Memory decay (update relevance scores and tiers)
echo "=== Memory decay ==="
uv run .claude/skills/autograph/scripts/engine.py decay . || echo "Memory decay failed (non-critical)"
cd "$PROJECT_DIR"

# Git commit
git add -A
git commit -m "chore: process daily $TODAY" || true
git push || true

# Send to Telegram
if [ -n "$REPORT_CLEAN" ] && [ -n "$CHAT_ID" ]; then
    echo "=== Sending to Telegram ==="
    RESULT=$(curl -s -X POST "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/sendMessage" \
        -d "chat_id=$CHAT_ID" \
        -d "text=$REPORT_CLEAN" \
        -d "parse_mode=HTML")

    # If HTML failed, send without formatting
    if echo "$RESULT" | grep -q '"ok":false'; then
        echo "HTML failed: $RESULT"
        curl -s -X POST "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/sendMessage" \
            -d "chat_id=$CHAT_ID" \
            -d "text=$REPORT_CLEAN"
    fi
fi

echo "=== Done ==="
