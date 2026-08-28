# Второй мозг — рабочие правила vault

Личное хранилище Александра: обследование зданий (IPC) + TRONIX.
Личность и стиль ассистента заданы в `deploy/brain-system.md` — здесь только
устройство vault и правила работы с файлами.

## БУТСТРАП КАЖДОЙ СЕССИИ

Прочитать по порядку, до любых действий:

1. `MEMORY.md` — долговременная память (профиль, решения, активный контекст)
2. `.session/handoff.md` — чем закончилась прошлая сессия
3. `daily/YYYY-MM-DD.md` — сегодня (и вчера, если сегодня пусто)
4. `goals/3-weekly.md` — ONE Big Thing недели

Не спрашивать разрешения — просто прочитать.

## КОНЕЦ ЗНАЧИМОЙ СЕССИИ

Дописать в сегодняшний `daily/`:

```markdown
## HH:MM [text]
Итог: что обсудили / решили / создали
- Решение: если было
- Создано: [[ссылка]]
- Следующий шаг: если есть
```

Обновить `MEMORY.md` — только если появилось новое решение, предпочтение,
факт или сменился активный контекст. Обновить `.session/handoff.md`:
последняя сессия, решения, незавершённое, следующие шаги, наблюдения
(`[friction]`, `[pattern]`, `[idea]`).

## Структура

| Каталог | Что внутри |
|---------|-----------|
| `daily/` | Сырой поток дня (`YYYY-MM-DD.md`), пишется ботом |
| `goals/` | Каскад целей: 3 года → год → месяц → неделя |
| `thoughts/` | Обработанные заметки: `tasks/ projects/ ideas/ learnings/ reflections/` |
| `MOC/` | Индексы (Maps of Content), строятся autograph |
| `summaries/` | Дневные и недельные сводки |
| `attachments/` | Файлы по датам: `attachments/YYYY-MM-DD/` |
| `templates/` | Шаблоны карточек |
| `business/` | Контрагенты и объекты обследования (вне git) |
| `projects/` | Проекты TRONIX и лиды (вне git) |

`business/` и `projects/` создаются по мере надобности; точка входа в
каждом — `_index.md`.

## Домены записи

| Домен | Признаки | Куда |
|-------|----------|------|
| Обследование (IPC) | объект, тендер, техзаключение, дефектная ведомость, надзор, эксперт, ГОСТ/СП | `thoughts/tasks/`, `business/` |
| TRONIX | 3D-печать, Shop, DW, Точка Контакта, материалы, себестоимость, Рома, Гена | `thoughts/`, `projects/` |
| Компания и команда | найм, процессы, финансы, юрлицо, бухгалтерия, Женя | `thoughts/projects/` |
| Личное | здоровье, режим, бюджет, отдых | `thoughts/reflections/` |

Подробные правила классификации:
`.claude/skills/dbrain-processor/references/classification.md`.

## Формат записи в daily

```markdown
## HH:MM [type]
Содержимое
```

Типы: `[voice]`, `[text]`, `[photo]`, `[document]`, `[forward]`.

## Карточки (autograph)

Скилл: `.claude/skills/autograph/SKILL.md`. Любая новая карточка:

```yaml
---
type: task|project|idea|note|crm|contact|object
description: >-
  Одна строка — то, что человек увидит в результатах поиска
tags: [tag1, tag2]        # 2–5 штук, lowercase
status: active|draft|pending|done|inactive
created: YYYY-MM-DD
updated: YYYY-MM-DD
# Автополя, руками не трогать:
last_accessed: YYYY-MM-DD
relevance: 0.85
tier: active
---
```

Правила:
- `description` обязателен и написан как поисковый сниппет, а не «заметка».
- `tags` обязательны, 2–5, через дефис.
- `status` ≠ `tier`: status — состояние дела, tier — память (автомат).
- Один факт живёт в одном месте. Всё остальное — `[[wikilinks]]`.
- Забывание: `uv run .claude/skills/autograph/scripts/engine.py decay .`
- Здоровье графа: `uv run .claude/skills/autograph/scripts/graph.py health .`

## Ежедневная обработка

`/process` в Telegram или таймер в 21:00. Скилл:
`.claude/skills/dbrain-processor/SKILL.md`. Три фазы — CAPTURE (разобрать
записи дня), EXECUTE (создать карточки и связи), REFLECT (сводка + MEMORY).

## Отчёты в Telegram

Только HTML: `<b>`, `<i>`, `<code>`, `<s>`, `<u>`, `<a>`. Никакого Markdown
и никаких таблиц с `|` — Telegram их не рендерит. До 4096 символов.

## Правила по типам файлов

`.claude/rules/`: `daily-format.md`, `thoughts-format.md`, `goals-format.md`,
`telegram-report.md`, `obsidian-markdown.md`, `weekly-reflection.md`.

## Агенты

| Агент | Задача |
|-------|--------|
| `note-organizer` | Навести порядок в vault, починить ссылки |
| `inbox-processor` | Разбор инбокса по GTD |

## Правила, выведенные на практике

1. Не переписывать работающий код без причины (KISS, DRY, YAGNI).
2. Не добавлять проверок, которых не просили.
3. Не предлагать решение, не посмотрев git log / diff.
4. Номера и редакции нормативов не цитировать по памяти — помечать
   `[сверить редакцию]`.
5. Проблемы обычно проще, чем кажутся.
