---
type: note
paths: "thoughts/reflections/YYYY-W*"
---

# Weekly Reflection Format

Rules for weekly system reflections (triggered on Sundays or by `/weekly`).

## Purpose

Analyze accumulated observations → find patterns → propose improvements.
This is the **operational learning loop** — the system learns from its own friction.

## When to Generate

- Every Sunday (automatically or via `/weekly`)
- When observations in `.session/handoff.md` reach ≥10

## File Location

`thoughts/reflections/YYYY-WNN-system-reflection.md`

## Template

```markdown
---
date: YYYY-MM-DD
type: reflection
description: "Week NN system analysis: N friction signals, M patterns found, K proposals"
tags: [system, reflection, weekly]
source: .session/handoff.md
related: []
---

# Week NN System Reflection

## Friction Patterns
<!-- Group similar observations from handoff.md -->
- **mcp-cli timeouts:** N occurrences — [root cause hypothesis]
- **Empty daily files:** N of 7 days — [pattern: weekends?]
- **Broken links:** N new this week — [source: CRM imports?]

## Improvements Applied
<!-- What was fixed this week -->
- [fix] Description of what was improved
- [fix] Another improvement

## Proposals
<!-- Concrete proposals for system improvements -->
1. [proposal] Description — target file: `path/to/file`
2. [proposal] Another proposal — target: `scripts/process.sh`

## Graph Health
Score: NN/100 (↑/↓ N vs last week)
- Orphans: N (was M)
- Broken links: N (was M)
- Avg links/file: X.XX
- Description coverage: Y%

## Observations Cleared
<!-- After reflection, clear processed observations from handoff.md -->
Moved N observations to this reflection file.
```

## Process

1. Read `.session/handoff.md` → collect `## Observations`
2. Read `.graph/health-history.json` → get this week's trend
3. Group observations by type (friction/pattern/idea)
4. Find recurring patterns (same issue >2 times)
5. Propose concrete improvements (file + change)
6. Write reflection file
7. Clear processed observations from handoff.md (keep unprocessed)
8. Add reflection to daily log

## Tags

Use `#system` tag for all system reflections.
Cross-reference with:
- `[[MEMORY.md]]` — if proposals become decisions
- `[[goals/3-weekly]]` — if proposals affect weekly focus
