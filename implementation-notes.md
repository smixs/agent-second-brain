# Implementation Notes — переход на персистентную tmux-сессию (выживание после 15.06.2026)

Живой журнал решений. Полный план: `docs/plan-survive-june15.md`.

## Контекст

С 15 июня 2026 `claude -p`/`--print`/Agent SDK уходят из лимитов подписки в отдельный платный credit. Проект целиком на `claude -p`. Решение: гонять **персистентную интерактивную сессию Claude Code** в tmux (остаётся на подписке). Фаза 1 — починить свой инстанс.

---

## 2026-06-07

### Decisions
- **Durable-state-first вместо ежедневного `/clear`** (по поправке пользователя). Ежедневный `/clear` убран. Полагаемся на встроенный auto-compact. Вся память — во внешних файлах (vault, MEMORY.md/agent-memory, handoff.md, SessionStore). Контракт сентинелов держим в `--append-system-prompt` + `vault/.claude/CLAUDE.md` (переживают compact/clear/краш) — поэтому компакт не ломает детект конца ответа. `/clear` остаётся только ручной командой recovery.
- **Правило памяти**: обновлять handoff + значимые факты после каждого *завершённого запроса/фазы* (НЕ каждого микрошага — токены + замусоривание agent-memory decay). Прописать в `brain-system.md` и `CLAUDE.md`.
- **Детект конца ответа** — сентинел с UUID (`<<<R:id>>> … <<<E:id>>>`) как primary, idle-prompt regex как fallback.
- **Кросс-процессный flock** (`~/.dbrain/pane.lock`) — обязателен: бот, process.sh и watchdog лезут в один pane; in-process Lock их не сериализует.

### Gotchas (из живого PoC на macOS)
- tmux 3.6b, claude **2.1.168**, node v26.0.0, uv 0.8.4.
- `claude auth status --json` → `{loggedIn:true, authMethod:"claude.ai", apiProvider:"firstParty", email:...}`. Значит `grep "Logged in"` в `setup.sh:579` СЛОМАН — нужен `jq -e '.loggedIn==true'`.
- `claude setup-token` существует: «Set up a long-lived authentication token (requires Claude subscription)», без localhost-redirect → headless-friendly. **Открытый вопрос (блокер №1)**: авторизует ли он ИНТЕРАКТИВНЫЙ путь или только `-p`. Проверять на VPS.
- ⚠️ На macOS `~/.claude/.credentials.json` ОТСУТСТВУЕТ (creds в Keychain). На Linux-VPS файл есть → doctor-проверка `expiresAt` через файл валидна только на Linux. Кросс-платформенный fallback: `claude auth status --json`.

### Spike findings (tmux+claude 2.1.168, live)
- **Trust-диалог** блокирует старт даже с `--dangerously-skip-permissions`: «Is this a project you ... trust? ❯1. Yes / 2. No». `ensure_session` шлёт Enter при детекте `trust` → грузится. Подтверждено: trust_handled+ready работают.
- **`capture-pane -p` — ЧИСТЫЙ текст** (без ANSI). Парсим ответ/состояние из него. `pane.log` (pipe-pane) — адский ANSI, только для liveness (mtime).
- **Маркеры состояний:** idle=`❯`; нижний якорь=`⏵⏵ bypass permissions on (shift+tab to cycle)`; старт-бокс=`Claude Code v2.1.168`; trust=`trust` + `Yes`.
- **🔴 Эхо ввода ломает наивный детект:** маркеры из промпта видны в input-боксе → ложное срабатывание. Решение: ждать ВТОРУЮ пару маркеров (эхо+ответ), брать последнюю; якорь на возврат `❯` idle. Дампы спайков → pytest-фикстуры.
- **Модель сессии: Opus 4.8 (1M), Claude Max.** Для 24/7 дорого по weekly-cap → рассмотреть `--model sonnet` при запуске сессии.
- `-S -` (full history) в READY-state дал пустоту (alternate screen scrollback) — для извлечения брать `-S -200`, не `-S -`.

### New requirements (2026-06-07, от пользователя)
- Вся работа — ОДИН PR из ветки в main. После зелёного e2e: bump v3.1 + GitHub release.
- Отдельный upgrade-скрипт: обновление существующих установок одной командой (tmux+deps, миграция systemd d-brain-*→dbrain-*, рестарт). Задачи #14, #15.

### Open questions (ответил сам)
- Гранулярность записи памяти: выбрал «после фазы/запроса», не «после микрошага» — баланс надёжности и стоимости/шума.

### Process (по требованию пользователя)
- **Строгий TDD на каждый шаг:** 🔴 red → 🟢 green → 👁 слепое ревью новым агентом → ♻️ рефактор → 🟢 green → ✅ атомарный коммит.
- Атомарные коммиты: только файлы шага (`git add <пути>`), НЕ `git add -A`. Без Claude attribution (глобальный CLAUDE.md OVERRIDE).
- Ветка: `feature/persistent-tmux-session` (создана). НЕ `main`. Push на public-репо — спрашивать.
- PoC/spike — discovery, НЕ коммитится.
- Инфра: pytest 9.0.2 + pytest-asyncio готовы. shellcheck отсутствует (поставить через brew для bash-шагов). tests/ создаётся в первом цикле.
- Чистая Python-логика → pytest. Bash → shellcheck/`bash -n`+smoke. systemd → `systemd-analyze verify`.

### Внимание при коммитах
- В рабочем дереве есть НЕ моё изменение `vault/.claude/CLAUDE.md` (правил пользователь) — НЕ включать в мои атомарные коммиты.

### TODO трекинг
См. task list (TaskCreate) — Фаза 1, 13 задач.
