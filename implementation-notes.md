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

### Live integration findings (claude_session, claude 2.1.168) — баги, что моки не ловят
1. `capture-pane -S -` и `-S -2000` → ПУСТО на tmux 3.6b; работает `-S -200` (вкл. scrollback).
2. Терял `kill()` при рефакторе — вернул + тест.
3. Trust-меню рисуется ВВЕРХУ экрана, низ пустой → classify искал в chrome(низ) → UNKNOWN. Фикс: trust по всему тексту (якорь на меню).
4. Footer (`bypass permissions`/`❯`) НЕ в последних строках (низ экрана пуст) → READY по footer-якорю глобально.
5. claude префиксует первую строку ответа `⏺ ` + отступы → маркер не line-start. Инвариант: маркер в КОНЦЕ строки (после него ничего), не в начале. Это и отличает ответ от inline-эхо.
→ Итог: live e2e `ask()` → 'PONG'. pane height=50 (footer у низа), capture `-S -200`, target = имя сессии (не `:0.0`, иначе base-index ломает).
TODO: ответы >~экрана читать из pane.log (сейчас capture -S -200).

### CLAUDE.md (vault) — не трогаю
В рабочем дереве несохранённые правки пользователя в `vault/.claude/CLAUDE.md`. Контракт сессии (маркеры/HTML/durable-memory) кладу в `deploy/brain-system.md` (--append-system-prompt, переживает compact). CLAUDE.md durable-state уже покрыт SESSION END PROTOCOL.

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
См. task list (TaskCreate) — Фаза 1, 15 задач.

---

## Статус реализации (2026-06-07)

**Готово локально (12/15), 88 тестов зелёные, ruff чист, guard проходит, live e2e `ask()`→'PONG':**
1. ✅ `tmux_parse.py` + `claude_session.py` (ядро, live-проверено)
2. ✅ `deploy/brain-system.md` (контракт сессии)
3. ✅ `processor.py` → session.ask (без claude -p)
4. ✅ `runtime.py` singleton + хендлеры do/process/weekly + scripts/weekly.py
5. ✅ `bot/main.py` ensure+sd_notify, `systemd_notify.py`
6. ✅ `config.py` + `.env.example` (session/tz/escape-hatch)
7. ✅ `pipeline.py` + `process.sh` shim (без claude -p)
8. ✅ `watchdog.py` (state-based hang, дебаунс, deferred recovery)
9. ✅ `doctor.py` (канарейка + локальные чеки)
10. ✅ `bin/dbrain` CLI
11. ✅ systemd units `dbrain-*` + timers + notify@ + tmux.conf (старые d-brain-* удалены)
12. ✅ `RouterSession` escape-hatch + `escape-hatch.sh` + `check-no-claude-p.sh` guard
14. ✅ `upgrade.sh` (миграция существующих установок)

**Требуют разрешения пользователя (outward/необратимо):**
13. ⏸ Деплой на VPS + e2e (нужен SSH-доступ; autonomy guardrail).
15. ⏸ Один PR в main + bump v3.1 + GitHub release. ВАЖНО: ветка отстаёт от origin/main на 2 коммита (README rewrite + setup guide) — перед PR ребейз/мерж на origin/main. Bump version (pyproject 1.0.0→3.1.0, vault CLAUDE.md System Version 3.0→3.1) и README-секцию про tmux/биллинг/upgrade делать в этой фазе после ребейза.

**Открытый блокер №1 (для Фазы 2 / go.sh свежей установки):** проверить, что `claude setup-token` авторизует ИНТЕРАКТИВНЫЙ путь, а не только -p. На своём VPS login уже есть, поэтому Фазу 1 не блокирует.

**Не трогал:** `vault/.claude/CLAUDE.md` (несохранённые правки пользователя), `formatters.py` (откатил ruff drive-by).

## 2026-06-10 — v3.0 S1: remove Todoist

- Decision: blind review found todoist instructions deep in dbrain-processor prose
  (SKILL.md body, phases/, references/) and rules/*.md. Triage: live paths removed
  now (mcp-config.json deleted, processor/config/runtime code, todoist-ai skill,
  goal-aligner agent, install.sh/setup.sh flows incl. whole install_mcp_cli);
  skill PROSE deferred to T12 where dbrain-processor is rewritten for autograph
  (avoids de-todoisting 600+ lines twice). weekly-digest.md dies in S3.
  pyproject description — S6.
- Gotcha: mcp-config.json's ONLY server was todoist → file deleted entirely
  (runtime.py guards with mcp.exists()).
- Gotcha: goal-aligner agent's sole purpose was todoist↔goals alignment → deleted,
  not trimmed.

## 2026-06-10 — v3.0 T8: liveness pair rewrite

- Decision: stall/hung redefined from "no pane.log bytes" to "no visible turn"
  (working spinner '(esc to interrupt)' absent). ask() and watchdog share the
  is_working() predicate; watchdog hung is persistence-based (_stuck_since),
  not instant — one observation never kills.
- VERIFY-LIVE: the '(esc to interrupt)' anchor must be confirmed against the
  live CLI version on ovh1 (like the pane-geometry notes). If the TUI renames
  the hint, is_working() goes blind — check during smoke.
- Gotcha: removed liveness_fn/_pane_log_mtime; pane.log stays (pipe-pane log)
  but is no longer a liveness signal.
