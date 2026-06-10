# HTML Report Template

## CRITICAL: Output Format

**Return RAW HTML text only. No markdown wrappers.**

WRONG (markdown code block):
```html
<b>Title</b>
```

CORRECT (raw HTML):
<b>Title</b>

Output goes directly to Telegram `parse_mode=HTML`.

## Allowed Tags

<b> or <strong> — bold
<i> or <em> — italic
<code> — inline code
<pre> — code blocks
<s> or <strike> or <del> — strikethrough
<u> — underline
<a href="url">text</a> — links

## FORBIDDEN

NO markdown: **, ##, -, *, backticks
NO code blocks with triple backticks
NO tables (Telegram doesn't support)
NO unsupported tags: div, span, br, p, table, tr, td

## Template

📊 <b>Обработка за {DATE}</b>

<b>🎯 Текущий фокус:</b>
{ONE_BIG_THING from goals/3-weekly.md}

<b>📓 Сохранено мыслей:</b> {N}
• {emoji} {title} → {category}/

<b>✅ Создано задач:</b> {M}
• {task_name} <i>({priority}, {due})</i>

<b>🏢 Business:</b>
• {client_name} — {action/status}
<i>{N} клиентов упомянуто</i>

<b>📅 Загрузка на неделю:</b>
Пн: {n} | Вт: {n} | Ср: {n} | Чт: {n} | Пт: {n} | Сб: {n} | Вс: {n}

<b>⚠️ Требует внимания:</b>
• {count} просроченных задач
• Цель "{goal}" без активности {days} дней

<b>🔗 Новые связи:</b>
• [[Note A]] ↔ [[Note B]]

<b>⚡ Топ-3 приоритета на завтра:</b>
1. {task} <i>({goal if aligned})</i>
2. {task}
3. {task}

<b>📈 Прогресс по целям:</b>
• {goal_name}: {progress}% {emoji}

---
<i>Обработано за {duration}</i>

## Section Rules

### Focus (🎯)
Read from goals/3-weekly.md, find "ONE Big Thing" section.
If not found: "Не задан — обновите goals/3-weekly.md"

### Thoughts (📓)
Count saved, list with category emoji:
💡 idea, 🪞 reflection, 🎯 project, 📚 learning

### Tasks (✅)
Count created, list with priority and due date.
Format: • Task name <i>(p2, friday)</i>

### Business Activity (🏢)
Show ONLY if client/project mentions exist.
- Max 5 clients
- If CRM status changed → add note
- Format: • {Client} — {action}
- Footer: <i>{N} клиентов упомянуто</i>

### Week Load (📅)
Call find-tasks-by-date for 7 days.
Format: Пн: 4 | Вт: 2 | ...

### Attention (⚠️)
Show only if issues exist.
Check overdue tasks and stale goals (7+ days no activity).

### Links (🔗)
Show only if new links created.
Format: • [[Note A]] ↔ [[Note B]]

### Priorities (⚡)
Get open task entries from the daily/project notes, sort by priority, show top 3.

### Goals Progress (📈)
Read goals/1-yearly-2026.md, show goals with recent activity.
Emojis: 🔴 0-25%, 🟡 26-50%, 🟢 51-75%, ✅ 76-100%

## Error Report

❌ <b>Ошибка обработки</b>

<b>Причина:</b> {error_message}
<b>Файл:</b> <code>{file_path}</code>

<i>Попробуйте /process снова</i>

## Empty Report

📭 <b>Нет записей для обработки</b>

Файл <code>daily/{date}.md</code> пуст.

<i>Добавьте записи в течение дня</i>

## Length Limit

Telegram max: 4096 characters.
If exceeds: truncate "Новые связи" first, then keep only top 3 goals.

## Validation Checklist

Before returning report:
1. All tags closed
2. No raw < or > in text (use &lt; &gt;)
3. No markdown syntax
4. No tables
5. Length under 4096 chars
