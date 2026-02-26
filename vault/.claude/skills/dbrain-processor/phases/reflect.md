# Phase 3: REFLECT

Read execute results. Generate HTML report. Update MEMORY. Write observations. Log to daily.

## Input
- `.session/capture.json` — from Phase 1
- `.session/execute.json` — from Phase 2
- `MEMORY.md` — long-term memory
- `.session/handoff.md` — session context
- `.graph/health-history.json` — vault health trend

## Task

### 1. Generate HTML report

Use the template from SKILL.md. Include:

- ONE Big Thing (from capture.json)
- Thoughts saved (from execute.json)
- Tasks created (with IDs)
- Process goals status
- Workload by day
- Vault Health score (from latest health-history.json entry)
- Top 3 priorities
- Observations (if any)

### 2. Log actions to daily

Append to `daily/{DATE}.md`:

```markdown
## HH:MM [text]
d-brain processing

**Tasks created:** N
- "Task content" (id: XXXX, priority, due)

**Thoughts saved:** M
- [[path/to/thought|Title]] — category

**CRM updated:** K
- [[business/crm/client]] — change description
```

### 3. Evolve MEMORY.md

Check if any information from today deserves long-term memory:
- New key decisions
- Pipeline changes (new lead, closed deal, status change)
- Financial changes
- Active Context updates

Rules:
- New info REPLACES outdated (don't append duplicates)
- Only write significant changes

### 4. Capture observations

If problems occurred during processing, append to `.session/handoff.md` under `## Observations`:

```markdown
- [friction] 2026-02-19: mcp-cli timeout on todoist — retried 3x
- [pattern] 2026-02-19: daily had only 2 entries — low activity day
```

### 5. Update handoff.md

Update session context:
- Last Session: what was processed
- Key Decisions: if any
- In Progress: incomplete items
- Next Steps: what to do next

## Output Format

Return RAW HTML report (no markdown, no code blocks). Goes directly to Telegram.

Follow the HTML template exactly:
- Only use: `<b>`, `<i>`, `<code>`, `<s>`, `<u>`, `<a>`
- NO: `<div>`, `<br>`, `<table>`, markdown syntax
- Max 4096 characters

### Vault Health section (add to report):

```html
<b>📊 Vault Health:</b> {score}/100
Orphans: {N} | Broken: {M} | Avg links: {X} | Desc: {Y}%
```

## CRITICAL

- Output is RAW HTML only
- No markdown syntax anywhere
- All HTML tags must be properly closed
