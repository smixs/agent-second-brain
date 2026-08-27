# Entry Classification

## Work Domains → Categories

Based on user's work context (see [ABOUT.md](ABOUT.md)):

### Обследования и инжиниринг (IPC)
Объекты, тендеры, техзаключения, надзор, проектирование, разовые контрагенты (фиксированного списка партнёров нет — компания определяется по контексту записи)

**Keywords:** обследование, объект, тендер, техзаключение, дефектная ведомость, надзор, проектирование, IPC, Industrial Project Company

**→ Category:** task (p1-p2) → vault task entry

### TRONIX
TRONIX Shop (текущий фокус, высокий приоритет) / TRONIX DW и Точка Контакта (низкий приоритет, просто на радаре)

**Keywords:** TRONIX, Троникс, Tronix Shop, Tronix DW, Точка Контакта, 3D-печать, маркетплейс, Рома, Гена

**→ Category:** task или idea → thoughts/ (Shop — приоритет выше, DW/Точка Контакта — ниже)

### Компания и команда
Найм, процессы, финансы и юр.вопросы обеих компаний (IPC + TRONIX)

**Keywords:** команда, найм, процесс, финансы, КПН, бухгалтерия, юрист, [[zhenya|Женя]]

**→ Category:** task или project (depends on urgency)

### Личное
Здоровье и рутина, личный бюджет, отношения, отдых

**Keywords:** зарядка, тренировка, сон, режим, бюджет, отдых, баня

**→ Category:** reflection или idea → thoughts/, или task если с конкретным действием

---

## Decision Tree

```
Entry text contains...
│
├─ Клиент/партнёр по обследованиям + дедлайн? ───> TASK (p1-p2)
│  (Integra Construction, Жилой фонд, тендер, объект, дедлайн)
│
├─ Operational/urgent? ──────────────────────────> TASK (p2-p3)
│  (нужно сделать, не забыть, позвонить, встреча)
│
├─ TRONIX Shop с конкретным действием? ──────────> TASK (p2) + флаг приоритета
│  (сайт, продажи, акция, запуск)
│
├─ TRONIX DW / Точка Контакта — просто упоминание? ─> IDEA (низкий приоритет)
│
├─ Strategic thinking? ──────────────────────────> PROJECT
│  (стратегия, план, долгосрочно)
│
├─ Personal insight? ────────────────────────────> REFLECTION
│  (понял, осознал, философия, здоровье, рутина)
│
└─ Идея без конкретного применения? ─────────────> IDEA
```

---

## Business Client Detection

Entry mentions any компанию/контрагента в контексте обследования, тендера или объекта (постоянного списка нет — любое название компании рядом с этими словами считается)?

```
├─ + deadline/urgency? → TASK (p1-p2) + client label
├─ + статус ("отправили предложение", "подписали", "выиграли")? → TASK + flag for CRM note
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
- Это усиливает экспертизу или репутацию IPC/TRONIX?
- Это приближает к постоянному потоку объёмов или к запуску TRONIX Shop?

Если да на 2+ вопроса → повысить приоритет.

---

## Photo Entries

For `[photo]` entries:

1. Analyze image content via vision
2. Determine domain:
   - Фото объекта, дефекта, техзаключения → Обследования и инжиниринг
   - Скриншот сайта/маркетплейса → TRONIX
   - Текст/статья → Личное или соответствующий домен
3. Add description to daily file

---

## Output Locations

| Category | Destination | Priority |
|----------|-------------|----------|
| task (обследования/IPC) | vault task entry | p1-p2 |
| task (TRONIX Shop) | vault task entry | p2 |
| task (TRONIX DW/Точка Контакта) | vault task entry | p3-p4 |
| task (компания/команда) | vault task entry | p2-p3 |
| task (личное) | vault task entry | p3-p4 |
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
thoughts/ideas/2026-09-05-tronix-shop-new-year-promo.md
thoughts/projects/2026-09-05-integra-construction-pilot-object.md
thoughts/learnings/2026-09-05-obsledovanie-report-format.md
```

---

## Thought Structure

Use preferred format:

```markdown
---
date: {YYYY-MM-DD}
type: {category}
domain: {Обследования и инжиниринг|TRONIX|Компания и команда|Личное}
tags: [tag1, tag2]
---

## Context
[Что привело к мысли]

## Insight
[Ключевая идея]

## Implication
[Что это значит для IPC/TRONIX/стратегии]

## Next Action
[Конкретный шаг — не абстрактный]
```

---

## Anti-Patterns (ИЗБЕГАТЬ)

При создании мыслей НЕ делать:
- Абстрактные рассуждения без Next Action
- Академическая теория без применения к IPC/TRONIX
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
## Обследования и инжиниринг
- [[2026-09-05-integra-construction-pilot-object]] - Пилотный объект по Integra Construction

## TRONIX
- [[2026-09-05-tronix-shop-launch-plan]] - План запуска сайта
```
