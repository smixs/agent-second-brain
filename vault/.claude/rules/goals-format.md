---
paths: "goals/**/*.md"
---

# Goals Format

Rules for goal files in `goals/` folder.

## File Structure

```
goals/
├── 0-vision-3y.md   # 3-year vision by life areas
├── 1-yearly-2025.md # Annual goals with quarterly breakdown
├── 2-monthly.md     # Current month priorities
└── 3-weekly.md      # This week's focus + ONE Big Thing
```

## Hierarchy Principle

Goals cascade from long-term to daily:

```
3-Year Vision (life direction)
    → Yearly Goals (annual objectives)
        → Monthly Focus (current priorities)
            → Weekly Plan (this week's actions)
                → Daily Tasks (today's daily note)
```

## Required Frontmatter

```yaml
---
type: vision | yearly | monthly | weekly
period: 2025 | 2024-12 | 2024-W51
updated: YYYY-MM-DD
---
```

## Progress Tracking

Use consistent progress format:

| Symbol | Meaning |
|--------|---------|
| 🔴 | 0-25% — Not started |
| 🟡 | 26-50% — In progress |
| 🟢 | 51-75% — Good progress |
| ✅ | 76-100% — Complete |

Example:
```markdown
| Goal | Progress | Status |
|------|----------|--------|
| Ship MVP | 65% | 🟢 |
| Fitness routine | 30% | 🟡 |
```

## ONE Big Thing

Weekly file MUST contain ONE Big Thing:

```markdown
## ONE Big Thing

> **If I accomplish nothing else, I will:**
> [Single most important outcome]
```

This is read by dbrain-processor for context.

## Goal Limits

- **Yearly:** Max 3 goals per life area
- **Monthly:** Max 3 top priorities
- **Weekly:** ONE Big Thing + 3 Must Do tasks

## Linking Goals to Tasks

When creating tasks, reference goals:

```markdown
- [ ] [Task] — Связь: [[1-yearly-2025#Career]]
```

## Stale Goal Warning

Goals without activity for 7+ days trigger warning in report.

Track "last touched" via:
- Task entry completion in the vault
- Note saved related to goal
- Progress % update

## Review Cadence

| Level | Review Frequency |
|-------|------------------|
| Vision | Quarterly |
| Yearly | Monthly |
| Monthly | Weekly |
| Weekly | Daily |
