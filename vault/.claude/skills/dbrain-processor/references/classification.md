# Entry Classification

## Work Domains → Categories

Based on user's work context (see [ABOUT.md](ABOUT.md)):

### Client Work
Брифы, стратегии, креатив, кампании, KPI, предложения

**Keywords:** [Client A], [Client B], [Client C], клиент, бриф, презентация, дедлайн, KPI

**→ Category:** task (p1-p2) → vault task entry

### AI & Tech
Инструменты, модели, промпты, пайплайны, агенты

**Keywords:** GPT, Claude, модель, агент, API, пайплайн, автоматизация, интеграция

**→ Category:** learning или project → thoughts/

### Product
Идеи, гипотезы, MVP, юнит-экономика

**Keywords:** продукт, SaaS, MVP, гипотеза, монетизация, юнит-экономика, стартап

**→ Category:** idea или project → thoughts/

### Company Ops
Команда, процессы, автоматизация, найм, управление, финансы

**Keywords:** команда, найм, процесс, HR, финансы, [Your Business], агентство

**→ Category:** task или project (depends on urgency)

### Content
Посты, идеи, тезисы для Telegram и LinkedIn

**Keywords:** пост, @yourbrand, LinkedIn, контент, тезис, статья

**→ Category:** idea → thoughts/ideas/ или task если с дедлайном

---

## Decision Tree

```
Entry text contains...
│
├─ Client brand or deadline? ────────────────────> TASK (p1-p2)
│  ([Client A], [Client B], клиент, дедлайн, презентация)
│
├─ Operational/urgent? ──────────────────────────> TASK (p2-p3)
│  (нужно сделать, не забыть, позвонить, встреча)
│
├─ AI/tech learning? ────────────────────────────> LEARNING
│  (узнал, модель, агент, интеграция)
│
├─ Product/SaaS idea? ───────────────────────────> IDEA или PROJECT
│  (продукт, MVP, гипотеза, SaaS)
│
├─ Strategic thinking? ──────────────────────────> PROJECT
│  (стратегия, план, R&D, долгосрочно)
│
├─ Personal insight? ────────────────────────────> REFLECTION
│  (понял, осознал, философия)
│
└─ Content idea? ────────────────────────────────> IDEA
   (пост, тезис, контент)
```

---

## Business Client Detection

Entry mentions a known client (see business-context.md)?

```
├─ + deadline/urgency? → TASK (p1-p2) + client label
├─ + статус ("отправили КП", "выиграли")? → TASK + flag for CRM note
├─ + встреча/звонок? → TASK (p2) + [[client]] link
└─ просто упоминание? → Add [[client]] link only
```

### CRM Status Keywords (для информации в отчёте)

| Keywords | Интерпретация |
|----------|---------------|
| "подписали", "выиграли", "получили" | Позитивный исход |
| "отказали", "проиграли", "не пошли" | Негативный исход |
| "отправили КП", "подали" | В процессе |
| "ждём ответ", "на рассмотрении" | Ожидание |

---

## Apply Decision Filters

Перед сохранением спроси:
- Это масштабируется?
- Это можно автоматизировать?
- Это усиливает экспертизу или бренд?
- Это приближает к продукту или SaaS?

Если да на 2+ вопроса → повысить приоритет.

---

## Photo Entries

For `[photo]` entries:

1. Analyze image content via vision
2. Determine domain:
   - Screenshot клиентского материала → Client Work
   - Схема/диаграмма → AI & Tech или Product
   - Текст/статья → Learning
3. Add description to daily file

---

## Output Locations

| Category | Destination | Priority |
|----------|-------------|----------|
| task (client) | vault task entry | p1-p2 |
| task (ops) | vault task entry | p2-p3 |
| task (content) | vault task entry | p3-p4 |
| idea | thoughts/ideas/ | — |
| reflection | thoughts/reflections/ | — |
| project | thoughts/projects/ | — |
| learning | thoughts/learnings/ | — |

---

## File Naming

```
thoughts/{category}/{YYYY-MM-DD}-short-title.md
```

Examples:
```
thoughts/ideas/2024-12-16-saas-pricing-model.md
thoughts/projects/2024-12-16-ai-agents-pipeline.md
thoughts/learnings/2024-12-16-claude-mcp-setup.md
```

---

## Thought Structure

Use preferred format:

```markdown
---
date: {YYYY-MM-DD}
type: {category}
domain: {Client Work|AI & Tech|Product|Agency Ops|Content}
tags: [tag1, tag2]
---

## Context
[Что привело к мысли]

## Insight
[Ключевая идея]

## Implication
[Что это значит для [Your Business]/продукта/стратегии]

## Next Action
[Конкретный шаг — не абстрактный]
```

---

## Anti-Patterns (ИЗБЕГАТЬ)

При создании мыслей НЕ делать:
- Абстрактные рассуждения без Next Action
- Академическая теория без применения к [Your Business]/продукту
- Повторы без синтеза (кластеризуй похожие!)
- Хаотичные списки без приоритетов
- Задачи типа "подумать о..." (конкретизируй!)

---

## MOC Updates

After creating thought file, add link to:
```
MOC/MOC-{category}s.md
```

Group by domain when relevant:
```markdown
## AI & Tech
- [[2024-12-16-claude-mcp-setup]] - MCP integration

## Product
- [[2024-12-16-saas-pricing-model]] - Pricing research
```

---

## ADD / SUPERSEDE / NOOP (temporal conflict)

For every fact worth keeping, pick one operation — this keeps a single non-contradictory
current truth per subject:

- **ADD** — genuinely new subject → create a card/entry by the autograph template.
- **NOOP** — already captured and unchanged → do nothing (avoid near-duplicates; grep first).
- **SUPERSEDE** — the new fact *contradicts* a current value on an existing card (job changed,
  moved city, status flipped, price revised). Do NOT just append the new value beside the old:
  1. **Rewrite** the card's current value — the frontmatter field and the top of the description.
     This is **Compiled Truth**: the living snapshot of what is true *now*.
  2. Move the OLD value to an append-only `## History` section as a dated line:
     `- 2026-03→06: TDI Group`. History is append-only and never edited.
  3. **Never leave two contradictory current values on the same subject.**
  If a whole card is obsolete (project renamed, decision reverted), set `status: superseded`
  and add `superseded_by: [[new-card]]`.

The deterministic scan writes `.graph/supersede-candidates.json` — same-entity cards with
conflicting scalar fields (company/role/status/…). During daily processing, read it and
resolve each listed group by superseding the stale card. Resolving these is a required step.

## Confidence

Tag each fact's certainty in frontmatter with `confidence:` so recall knows how hard to assert:

- **EXTRACTED** — the user stated it directly → assert it when recalling.
- **INFERRED** — you deduced it → hedge when recalling ("похоже, ты…").
- **AMBIGUOUS** — unclear or conflicting source → flag it.
