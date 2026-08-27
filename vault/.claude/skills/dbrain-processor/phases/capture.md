# Phase 1: CAPTURE

Read daily entries, classify them, and output structured JSON.

## Input
- `daily/{DATE}.md` — today's entries
- `goals/3-weekly.md` — current week focus
- `goals/2-monthly.md` — monthly priorities
- `goals/1-yearly-2026.md` — yearly goals

## Task

1. Read `daily/{DATE}.md`
2. For each entry (## HH:MM [type] block), classify:
   - **task** — actionable item → will become a vault task entry
   - **idea** → will be saved to thoughts/ideas/
   - **reflection** → thoughts/reflections/
   - **learning** → thoughts/learnings/
   - **project** → thoughts/projects/
   - **crm_update** — mentions business client → update CRM
   - **skip** — already processed or not actionable
3. Detect entity mentions (company names, people, projects)
4. Align with goals (which goal does this serve?)

## Output Format

Print ONLY valid JSON (no markdown, no explanation):

```json
{
  "date": "2026-09-05",
  "one_big_thing": "Integra Construction: получить пробный объём и назначить встречу",
  "entries": [
    {
      "time": "10:30",
      "type": "voice",
      "content": "Позвонил в Integra Construction, обсудили детали пилотного объекта",
      "classification": "task",
      "task_content": "Follow-up Integra Construction: отправить детали по пилотному объекту",
      "task_priority": 2,
      "task_due": "tomorrow",
      "entities": ["business/crm/integra-construction"],
      "goal_alignment": "ONE Big Thing"
    },
    {
      "time": "14:00",
      "type": "text",
      "content": "TRONIX Shop лучше запускать с новогодней акции",
      "classification": "idea",
      "title": "Новогодняя акция как точка входа для TRONIX Shop",
      "description": "Сезонный спрос под Новый год — шанс залететь красиво с первыми продажами.",
      "category": "ideas",
      "tags": ["tronix", "marketing"],
      "entities": ["projects/tronix-shop"],
      "goal_alignment": "yearly/Career & Business"
    }
  ],
  "stats": {
    "total_entries": 5,
    "tasks": 2,
    "thoughts": 2,
    "crm_updates": 1,
    "skipped": 0
  }
}
```

## Classification Rules

### Task indicators
- "нужно", "надо", "сделать", "позвонить", "отправить", "подготовить"
- Deadline mentions (завтра, в пятницу, до конца недели)
- Follow-up mentions

### Thought indicators
- Insights, patterns, observations
- "понял что", "интересно что", "заметил"
- No clear action required

### CRM indicators
- Company name mention (known clients from CRM)
- Deal/project status change
- Meeting/call with client

### Process goal formulation
When creating task_content, prefer PROCESS over OUTCOME:
- WRONG: "Закрыть сделку с Integra Construction"
- RIGHT: "Отправить follow-up Integra Construction: статус по пилотному объекту"

### Prose-as-title for thoughts
When creating thought titles, use CLAIMS not topic labels:
- WRONG: "TRONIX Shop маркетинг" (topic label)
- RIGHT: "Новогодняя акция как точка входа для TRONIX Shop" (specific claim)
Test: "Since [[title]], ..." should read naturally.

## Important
- Mark entries with `<!-- ✓ processed -->` as "skip"
- Output ONLY JSON — no explanation, no markdown wrapping
