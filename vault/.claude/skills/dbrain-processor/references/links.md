# Wiki-Links Building

## Purpose

Build connections between notes to create a knowledge graph.

## When Saving a Thought

### Step 1: Search for Related Notes

Search thoughts/ for related content:

```
Grep "keyword1" in thoughts/**/*.md
Grep "keyword2" in thoughts/**/*.md
```

Keywords to search:
- Main topic of the thought
- Key entities (people, projects, technologies)
- Domain terms

### Step 2: Check MOC Indexes

Read relevant MOC files:

```
MOC/
├── MOC-ideas.md
├── MOC-projects.md
├── MOC-learnings.md
└── MOC-reflections.md
```

Find related entries.

### Step 3: Link to Goals

Check if thought relates to goals:

```
Read goals/1-yearly-2026.md
Find matching goal areas
```

### Step 4: Add Links to Note (with context)

In the thought file, add **typed relationships** — each link explains WHY it's connected:

**In frontmatter (for graph analysis):**
```yaml
related:
  - "[[thoughts/ideas/2026-09-05-tronix-shop-launch]]"
  - "[[goals/1-yearly-2026#Career & Business]]"
```

**In content (inline):**
```markdown
This connects to [[TRONIX Shop Launch Plan]] we explored earlier.
```

**In Related section (with context phrases):**
```markdown
## Related
- [[thoughts/ideas/tronix-shop-launch|TRONIX Shop Launch Plan]] — extends: новогодняя акция
- [[business/crm/integra-construction|Integra Construction]] — context: похожий подход к пилотному объекту
- [[goals/1-yearly-2026#Career & Business]] — supports: годовая цель по TRONIX Shop
```

### Relationship Types

Use context phrases after `—` to explain the connection:

| Type | When to use | Example |
|------|------------|---------|
| extends | Builds on another idea | `— extends: добавляет новогоднюю акцию к плану запуска` |
| context | Background/origin of idea | `— context: возникло из переговоров с Integra Construction` |
| supports | Aligns with a goal | `— supports: годовая цель по TRONIX Shop` |
| contradicts | Challenges existing note | `— contradicts: предыдущий подход был другим` |
| enables | Makes something possible | `— enables: автоматические отчёты по обследованиям` |
| requires | Dependency | `— requires: найден человек под TRONIX Shop` |

### Step 5: Update MOC Index

Add new note to appropriate MOC:

```markdown
# MOC: Ideas

## Recent
- [[thoughts/ideas/2026-09-05-tronix-shop-launch.md]] — Новогодняя акция как точка входа

## By Topic
### TRONIX
- [[thoughts/ideas/2026-09-05-tronix-shop-launch.md]]
```

### Step 6: Add Backlinks

In related notes, add backlink to new note if highly relevant.

## Link Format

### Internal Links
```markdown
[[Note Name]]                    # Simple link
[[Note Name|Display Text]]       # With alias
[[folder/Note Name]]             # With path
[[Note Name#Section]]            # To heading
```

### Link to Goals
```markdown
[[goals/1-yearly-2026#Career & Business]]
[[goals/3-weekly]] — ONE Big Thing
```

---

## Business Entity Links

### Формат связей

| Тип | Формат | Пример |
|-----|--------|--------|
| Клиент | `[[business/crm/{name}\|Display]]` | `[[business/crm/integra-construction\|Integra Construction]]` |
| Проект | `[[projects/{name}\|Display]]` | `[[projects/tronix-shop\|TRONIX Shop]]` |
| CRM Lead | `[[business/crm/{name}\|Display]]` | `[[business/crm/zhiloy-fond\|Жилой фонд]]` |

### Где добавлять связи (с typed context)

**В daily file (комментарий):**
```markdown
## 10:30 [voice]
Позвонил в Integra Construction по проекту
<!-- связь: [[business/crm/integra-construction]] -->
```

**В thoughts (Related section с context phrases):**
```markdown
## Related
- [[business/crm/zhiloy-fond|Жилой фонд]] — context: обсуждение условий субподряда
- [[projects/tronix-shop|TRONIX Shop]] — extends: план новогодней акции
```

**В task-записи (контекст):**
```
Description: "Клиент: [[business/crm/integra-construction|Integra Construction]]"
```

---

## Report Section

Track new links created:

```
<b>🔗 Новые связи:</b>
• [[Note A]] ↔ [[Note B]]
• [[New Thought]] → [[Related Project]]
```

## Example Workflow

New thought: "Новогодняя акция — хороший способ запустить TRONIX Shop"

1. **Search:**
   - Grep "TRONIX Shop" в thoughts/ → находит [[TRONIX Shop Launch Plan]]
   - Grep "акция" в thoughts/ → нет результатов
   - Grep "новогодняя" → нет результатов

2. **Check MOC:**
   - MOC-ideas.md has "TRONIX" section

3. **Goals:**
   - 1-yearly-2026.md has "Career & Business" goal (Goal 2: Запуск TRONIX Shop)

4. **Create links:**
   ```yaml
   related:
     - "[[thoughts/ideas/tronix-shop-launch-plan.md]]"
     - "[[goals/1-yearly-2026#Career & Business]]"
   ```

5. **Update MOC-ideas.md:**
   ```markdown
   ### TRONIX
   - [[thoughts/ideas/2026-09-05-tronix-new-year-promo.md]] — новогодняя акция для запуска
   ```

6. **Report:**
   ```
   <b>🔗 Новые связи:</b>
   • [[Новогодняя акция]] ↔ [[TRONIX Shop Launch Plan]]
   ```

## Orphan Detection

A note is "orphan" if:
- No incoming links from other notes
- No related notes in frontmatter
- Not listed in any MOC

Flag orphans for review:
```
<b>⚠️ Изолированные заметки:</b>
• [[thoughts/ideas/orphan-note.md]]
```
