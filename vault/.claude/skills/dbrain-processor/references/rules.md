# Critical Processing Rules

See [ABOUT.md](ABOUT.md) for user context and preferences.

## Rule 1: Skip Processed Entries

```
If entry contains `<!-- ✓ processed` → SKIP COMPLETELY
```

Check AFTER each `## HH:MM` header for the marker.

## Rule 2: Every Task = Date

**NEVER create a task without `dueString`:**

| Text | dueString |
|------|-----------|
| завтра | tomorrow |
| в пятницу | friday |
| на этой неделе | friday |
| в четверг | thursday |
| 15 января | January 15 |
| NOT SPECIFIED | in 3 days |

## Rule 3: Check Duplicates

**BEFORE creating any task:**

1. Call `find-tasks` with key words from task
2. If similar task exists → **DO NOT CREATE**
3. Mark as: `<!-- ✓ processed: task (duplicate) -->`

## Rule 4: Consider Workload

**BEFORE creating tasks:**

1. Call `find-tasks-by-date` with `startDate: "today"`, `daysCount: 7`
2. Count tasks per day
3. If target day has 3+ tasks → shift to next day with less load

## Rule 5: Mark After Processing

After EACH processed entry, add marker:

```markdown
<!-- ✓ processed: {category} -->
```

For tasks with details:
```markdown
<!-- ✓ processed: task → vault: {name} {priority} {date} -->
```

## Rule 6: Apply Decision Filters

Before saving any thought or task, check:
- Это масштабируется?
- Это можно автоматизировать?
- Это усиливает экспертизу [Your Business]?
- Это приближает к продукту/SaaS?

If 2+ yes → boost priority.

## Rule 7: Avoid Anti-Patterns

NEVER create:
- Абстрактные задачи без Next Action ("Подумать о...")
- Хаотичные списки без приоритетов
- Повторы без синтеза
- Академическая теория без применения

See [ABOUT.md](ABOUT.md) → Anti-Patterns section.

---

## Checklist Before Completion

- [ ] All new entries processed
- [ ] No duplicate task entries
- [ ] All tasks have dates and concrete actions
- [ ] Decision filters applied
- [ ] Anti-patterns avoided
- [ ] MOC files updated
- [ ] Report generated
