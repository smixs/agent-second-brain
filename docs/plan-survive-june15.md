# Финальный архитектурный план: D-Brain, который переживёт 15 июня

> Сгенерировано multi-agent workflow (17 агентов: 6 ресёрч → 3 дизайна → 3 судьи → 4 стресс-теста → синтез). Победившая архитектура: **KISS-Installer** (одна tmux-сессия + один Python-супервизор, три понятия). Найдено 50 дыр (36 critical/high), все critical/high закрыты ниже.

## 1. Краткое резюме

**Что строим.** Персональный Telegram-ассистент («второй мозг») на $5 VPS, который 24/7 принимает голос/текст, разбирает их через Claude Code и пишет в Obsidian-vault + Todoist. Сегодня каждый запрос вызывает `claude --print -p` (горячий путь — `processor.py`, дневной конвейер — `process.sh`). После **15 июня 2026** любой вызов с флагом `-p`/`--print` уходит в новый платный пул Agent SDK credit (Pro $20, Max 5x $100, Max 20x $200/мес, без переноса, биллинг по полным API-ставкам). Интерактивный `claude` в терминале остаётся на подписке без изменений.

**Почему переживёт 15 июня.** Мы убираем `-p` из горячего пути полностью. Вместо порождения нового процесса на каждый запрос мы держим **один долгоживущий интерактивный `claude`** в tmux-сессии и «печатаем» в него промпты через инъекцию клавиш (bracketed-paste). Граница биллинга у Anthropic — это буквально наличие флага `-p`; интерактивная сессия, управляемая инъекцией клавиш, остаётся в пуле подписки. `-p` остаётся **только** в одном месте — аварийном fallback через `ANTHROPIC_BASE_URL`, который включается одной переменной окружения.

**Три понятия для пользователя.** Бот (говорит с Telegram), Мозг (постоянная сессия Claude в tmux), Доктор (ежедневный осмотр). Одна команда после установки — `dbrain`.

**Durable-state-first (правка от 2026-06-07).** Контекст сессии — расходный, вся память во внешних файлах (`vault/`, `MEMORY.md` через agent-memory, `handoff.md`, `SessionStore`). Поэтому **ежедневный `/clear` НЕ нужен** — мы полагаемся на встроенный auto-compact и не воюем с ним. Единственный риск компакта — потеря контракта сентинелов — снимается тем, что контракт живёт в `--append-system-prompt` + `vault/.claude/CLAUDE.md` (Claude Code переинжектит их после compact/clear/краша). Правило **«после каждого завершённого запроса/фазы обновлять память (handoff + значимые факты)»** прописано в `brain-system.md` и `CLAUDE.md`. `/clear` остаётся только ручной командой для recovery (`dbrain clear` / состояние «contract-lost»).

**Честная оговорка (ToS).** Управление интерактивной сессией через инъекцию клавиш для 24/7-бота — серая зона: формально технически не детектится сегодня, но растягивает формулировку Anthropic «ordinary, individual usage», и Anthropic оставляет за собой право на enforcement «без предупреждения». Поэтому fallback через `ANTHROPIC_BASE_URL` — не аспирация, а **протестированный путь**, и в README + инсталлятор встроен явный дисклеймер риска. Репозиторий публичный и легко фингерпринтится — поэтому имя tmux-сессии, токены-маркеры и время суточного `/clear` **рандомизируются на каждой установке**.

---

## 2. Архитектура

```
                         ┌──────────────────────────────────────────────┐
                         │                  Telegram                     │
                         └───────────────────────┬──────────────────────┘
                                                  │ long-poll (aiogram)
                                                  ▼
    ┌─────────────────────────────────────────────────────────────────────────┐
    │  dbrain-bot.service  (systemd --user, Type=notify, Restart=always)        │
    │  ┌───────────────────────────────────────────────────────────────────┐   │
    │  │  aiogram handlers  →  ОДИН модуль  claude_session.py               │   │
    │  │     (singleton ClaudeSession + asyncio.Lock в процессе)            │   │
    │  │     bot.ask() ── flock(pane.lock) ── send-keys → poll sentinel     │   │
    │  └──────────────┬────────────────────────────────────────────────────┘   │
    │   sd_notify WATCHDOG=1 каждый цикл (WatchdogSec=180)                       │
    └──────────────────┼──────────────────────┬───────────────────────────────┘
                       │                        │
   flock ~/.dbrain/pane.lock (КРОСС-ПРОЦЕССНЫЙ мьютекс — единственный путь к pane)
                       │                        │
                       ▼                        ▼
    ┌──────────────────────────────┐   ┌──────────────────────────────────────┐
    │  tmux session "$BRAIN"       │   │  claude_session.py  __main__ CLI       │
    │  (имя рандомизировано)        │   │  `python -m d_brain.claude_session     │
    │  ┌────────────────────────┐  │   │     ask --file phaseN.txt`             │
    │  │ claude (INTERACTIVE)    │◀─┼───┤  ← дневной/недельный конвейер          │
    │  │  --dangerously-skip-... │  │   │     через ТУ ЖЕ locked-обёртку         │
    │  │  --mcp-config ...       │  │   └──────────────────────────────────────┘
    │  │  (Todoist MCP child)    │  │              ▲
    │  │  ❯ idle prompt          │  │              │ ExecStart (locked path)
    │  └────────────────────────┘  │   ┌──────────┴───────────────────────────┐
    │  pipe-pane → pane.log (mtime)│   │ systemd TIMERS (OnCalendar, TZ-aware, │
    └──────────────┬───────────────┘   │   Persistent=true — catch-up)         │
                   │                    │  (NO daily-clear — durable-state-first)│
       ready-флаг  │  heartbeat (3-ий   │  • doctor        08:00                 │
       (~/.dbrain) │   сигнал, не       │  • process       21:00                 │
                   ▼   основной)        │  • weekly        Fri 06:00            │
    ┌──────────────────────────────┐   └───────────────────────────────────────┘
    │ dbrain-watchdog.service       │
    │ (systemd --user, Type=notify, │   ЛИВНЕСС, НЕ расписание:
    │  Restart=always, WatchdogSec) │   • DEAD: has-session + pane_dead + kill -0
    │  каждые 15с, ВСЕ внеш.вызовы   │   • HUNG: triple-gate (inflight + spinner
    │  с timeout; sd_notify; flock   │       stuck + pane.log mtime stale)
    │  на ensure_session()          │   • RATE-LIMIT / LOGGED-OUT: НЕ убивать
    │  STATUS.md ← единый предикат   │   • disk-full: СТОП-рестарт + алерт
    └──────────────┬───────────────┘
                   │ раз в день
                   ▼
    ┌──────────────────────────────┐        Telegram
    │  doctor.py                    │ ── green/red ──▶ admin chat
    │  • канарейка В ТОТ ЖЕ pane    │        + healthcheck.io ping (out-of-band)
    │    (1 ход, ~0 RAM)            │
    │  • + cold-start 2-я сессия    │
    │    ТОЛЬКО для проверки auth   │
    │  • MCP-проба, git, RAM, disk, │
    │    linger, TZ, версия CLI     │
    └──────────────────────────────┘

  Fallback:  DBRAIN_MODE=router  → escape-hatch.sh → claude -p через ANTHROPIC_BASE_URL
             (нужен ОТДЕЛЬНЫЙ API-ключ, НЕ подписочный OAuth)
```

---

## 3. Компоненты

| Компонент | Файл | Назначение (одной строкой) |
|---|---|---|
| **claude_session.py** | `src/d_brain/services/claude_session.py` | Единственная абстракция к tmux-pane: Python-API (`ask`, `ensure_session`, `is_healthy`, `clear`, `detect_state`) + `__main__` CLI — бот, конвейер и доктор ходят через ОДИН код с кросс-процессным flock. |
| **Бот** | `src/d_brain/bot/*` (правка) | Без изменений aiogram-каркас; `ClaudeProcessor` теперь зовёт `session.ask()` вместо `subprocess`; на старте — `ensure_session()` и `sd_notify`. |
| **watchdog.py** | `src/d_brain/watchdog.py` | Только ливнесс/восстановление каждые 15с (НЕ расписание): DEAD/HUNG/rate-limit/logged-out/disk-full детекторы, пишет единый `STATUS.md`. |
| **doctor.py** | `src/d_brain/doctor.py` | Ежедневная самодиагностика: end-to-end канарейка + cold-start проба auth + MCP/git/RAM/disk/TZ/linger/версия CLI → green/red в Telegram. |
| **dbrain CLI** | `bin/dbrain` → `/usr/local/bin/dbrain` | Единственная команда для человека: `status / restart / logs / doctor / clear / login / repair / attach`. |
| **brain-system.md** | `deploy/brain-system.md` | Контракт сессии: маркеры-сентинелы, правила HTML-вывода, указатель на skill. Дублируется в `vault/.claude/CLAUDE.md` (переживает `/clear`). |
| **systemd units** | `deploy/*` | 2 сервиса (`dbrain-bot`, `dbrain-watchdog`, оба `--user`, `Type=notify`) + 4 таймера с `Persistent=true` + 1 notify-шаблон `OnFailure`. |

---

## 4. Жизненный цикл сессии

**START (boot/install).** `ensure_session()` под flock `~/.dbrain/ensure.lock`:
1. `tmux new-session -d -s "$BRAIN" -x 220 -y 50` (имя из `~/.dbrain/brain.name`, рандомизировано при установке); `set-option history-limit 50000`; `remain-on-exit off`.
2. Запуск **с MCP**: `claude --dangerously-skip-permissions --mcp-config <abs>/mcp-config.json --append-system-prompt-file ~/.dbrain/brain-system.md`, в окружении `MCP_TIMEOUT=30000`, `MAX_MCP_OUTPUT_TOKENS=50000`, `CLAUDE_CONFIG_DIR=$HOME/.claude`, `DISABLE_AUTOUPDATER=1`. **Без `-p`.**
3. `pipe-pane` → `~/.dbrain/pane.log` (байтовый поток для ливнесс).
4. Ждём idle-prompt → отправляем bootstrap-промпт (читает MEMORY.md/today/yesterday/weekly/handoff.md).
5. **Verify-ход:** `call mcp__todoist__user-info` — подтверждаем, что MCP-инструменты загружены.
6. Только после успеха пишем `~/.dbrain/ready`. Пока флага нет — бот отвечает «Просыпаюсь, ~30 секунд…», НЕ инъектит в неготовый pane.

**Детект конца ответа (маркеры).** ПЕРВИЧНЫЙ сигнал — **сентинел**: модели задан контракт оборачивать ответ в `<<<R:id>>> … <<<E:id>>>`, где `id` — UUID на запрос. `ask()` записывает смещение строк pane ДО отправки, сканирует ТОЛЬКО новые строки на `<<<E:id>>>` с конкретным id (исключает stale-маркер прошлого хода). Idle-prompt regex (`❯`/`>`) — только fallback. **Soft-success:** если `<<<E:id>>>` не пришёл, но idle-prompt вернулся с новым текстом и нет spinner — берём текст между смещением и idle-prompt (деградация вместо kill).

**RESUME (после краха/перезагрузки).** Всегда FRESH-старт (не `--resume`): многодневный JSONL — документированный crash-loop, а durable-state живёт в vault + CLAUDE.md + handoff.md. Каждый fresh-старт **reseed из `vault/.session/handoff.md` + STATUS.md** — конверсационная непрерывность восстанавливается почти бесплатно.

**КОНТЕКСТ (durable-state-first, без принудительного clear).** Ежедневный `/clear` убран. Полагаемся на встроенный **auto-compact** Claude Code и не воюем с ним: вся durable-память во внешних файлах (vault, `MEMORY.md`, `handoff.md`, `SessionStore`), поэтому потеря conversational-контекста при компакте безболезненна. Контракт сентинелов + правила вывода живут в `--append-system-prompt` + `vault/.claude/CLAUDE.md` — Claude Code переинжектит их после compact/clear/краша, значит компакт не ломает детект конца ответа. Парс по сентинелу с UUID игнорирует баннер компакта (в нём нет `<<<E:id>>>`). Отдельное состояние **«contract-lost»** (ответ без сентинела при вернувшемся idle) → пересылаем system-prompt и повторяем, НЕ даём watchdog убить как HUNG. `/clear` остаётся **только ручной** командой recovery (`dbrain clear`).

**Правило памяти (в `brain-system.md` + `CLAUDE.md`).** После каждого **завершённого запроса/фазы** (НЕ каждого микрошага — иначе токены + замусоривание agent-memory decay) Мозг обновляет `handoff.md` + пишет значимые факты через agent-memory. Это и есть «прописать в инструкции, чтобы память обновлялась», вместо костыля с clear.

---

## 5. Отказоустойчивость

| Отказ | Как детектим | Как восстанавливаемся |
|---|---|---|
| **CRASH (claude вышел)** | `has-session`=1 ИЛИ `#{pane_dead}`=1 ИЛИ `kill -0 $(pane_pid)` падает (3-слойная проверка) | watchdog `ensure_session()` под flock за ≤15с, reseed из handoff.md, Telegram «мозг перезапущен». Теряется только in-flight запрос. |
| **HUNG-but-alive** | **Triple-gate:** `inflight.lock` есть **И** `pane.log` mtime stale (нет байтов — primary, модель не подавит) **И** spinner-слово застряло без idle-prompt. Порог `≥ DEFAULT_TIMEOUT=1200s` для конвейера, короче для чата (per-job, НЕ глобальные 180s). | Сначала Ctrl-C → перепроверка idle (abort ≠ kill). Если не вернулся — kill+recreate. Никогда не Ctrl-C, пока байты текут. |
| **OOM-kill** | watchdog видит мёртвую сессию | Для 512MB: `ManagedOOMMemoryPressure=off` на slice мозга (systemd-oomd — cgroup-killer, OOMScoreAdjust не влияет); watchdog в ОТДЕЛЬНОМ slice; per-window cgroup; **zram обязателен** (FRACTION=0.5, lz4, `vm.swappiness=10`); `MemoryHigh` (мягкий), НЕ `MemoryMax`. |
| **REBOOT** | таймеры с `Persistent=true` догоняют пропуски | **Единая модель сервисов** `--user`+verified `loginctl enable-linger` (доктор проверяет `Linger==yes`). Текущий разнобой (бот=system, watchdog=user) удалён. |
| **CONTEXT OVERFLOW** | встроенный auto-compact Claude Code | Не воюем с компактом (durable-state-first): контракт сентинелов в system-prompt+CLAUDE.md переживает компакт; verbose-вывод инструментов → в файлы, не в контекст; память обновляется после каждой фазы. Принудительный `/clear` НЕ используется. |
| **AUTH EXPIRY (logged out)** | doctor end-to-end канарейка (НЕ `claude auth status` — он лжёт `loggedIn:true` на истёкшем токене); парс `~/.claude/.credentials.json` `expiresAt` — алерт за **48ч**. | Telegram-red; **re-login через чат** (см. §7), не SSH. `ask()` ловит logged-out signature → отвечает пользователю, НЕ висит. |
| **RATE LIMIT (5h/weekly)** | парс pane на «limit reached»/«resets at»/«weekly» — **ОТДЕЛЬНОЕ состояние, не HUNG** | НЕ kill (усугубляет). «rate-limited until T», ответ «Лимит исчерпан, вернусь в HH:MM», пауза конвейера, подавление restart-алертов. Доктор — amber. |
| **DISK FULL** | watchdog проверяет free disk КАЖДЫЙ цикл | СТОП-рестарт (рестарт не чинит) + red «диск полон, dbrain repair». logrotate на pane.log, `cleanupPeriodDays` на JSONL, `git gc`, `journald SystemMaxUse`. |
| **WATCHDOG/BOT hung** | оба `Type=notify` + `WatchdogSec`; каждый цикл `sd_notify`; ВСЕ внешние вызовы с `timeout`; взаимная проверка heartbeat | systemd убивает SIGABRT и рестартит. |
| **CRASH-LOOP** | `StartLimitBurst=5`/`IntervalSec=300`; backoff в wrapper если systemd <254 | `OnFailure=` независимый notify-юнит (только curl+токен) шлёт алерт даже при burst-trip. Реплицировать PATH/env из process.sh в юниты. |
| **CLI AUTO-UPDATE ломает TUI** | doctor логирует `claude --version` day-over-day | **Пиннинг** `@anthropic-ai/claude-code@X.Y.Z` + `DISABLE_AUTOUPDATER=1`; сентинел-детект (не зависит от TUI-хрома) primary; circuit-breaker на N провалов → FREEZE + алерт. |
| **skip-permissions отказ под root** | `ask()` ловит root-refusal banner | Инсталлятор детектит `uid==0` → non-root сервис-юзер. Distinct ошибка, НЕ recreate-loop. |
| **MCP (Todoist) умер** | verify-ход на старте + MCP-проба доктора | Пиннинг версии MCP-пакета (не `npx -y` latest); при провале бот честно «создание задач недоступно». |
| **STALE tmux socket** | `new-session` упал | `kill-session 2>/dev/null; new-session` при dead; `… || (tmux kill-server; new-session)` при битом сокете. |
| **NETWORK/Telegram down** | aiogram ретраит; доктор пишет STATUS.md | Отчёт в файл ДО side-effects; отправка — отдельный ретраемый шаг (идемпотентность — нет двойных Todoist-задач). healthcheck.io → email если Telegram мёртв. |
| **ESCAPE HATCH (закрыли интерактив)** | — | `DBRAIN_MODE=router` → отдельный API-ключ, `claude -p` через `ANTHROPIC_BASE_URL`. Реверсивный toggle. |

---

## 6. Ежедневная самодиагностика (Доктор)

`dbrain-doctor.timer` (`OnCalendar`, `Persistent=true`) в 08:00 локального — НЕ из watchdog-clock.

**Проверяет:**
1. **End-to-end канарейка в ТОТ ЖЕ `brain` pane** («Reply with exactly DBRAIN_OK») — authoritative-сигнал auth+модель+plumbing, единственное что ловит молча истёкший login. Парсер различает: login-ошибку / rate-limit / subscription-expired / timeout — каждая свой red+fix.
2. **Cold-start вторая сессия** (короткоживущая) — ТОЛЬКО проверка «холодный старт + auth»; **gated** (пропустить если `inflight` или RAM мало — чтоб не вызвать OOM); убить сразу. **Никогда `-p`**. Канарейки из pane и cold-start должны СОВПАСТЬ.
3. Локальные дешёвые: `git push --dry-run` exit 0; `credentials.json expiresAt` (⚠️ только Linux — на macOS creds в Keychain, файла нет); RAM>80MB; disk>500MB; все ключи `.env`; оба сервиса active; `Linger==yes`; TZ; `claude --version`; MCP-проба.
4. **Billing-drift (после 15 июня):** трекать потребление Agent SDK credit — алерт если интерактив неожиданно его тратит.

**Алертит:** одно сообщение в admin chat. GREEN с метриками / RED с точным one-liner для нетехнического человека. Доктор — финальный шаг инсталлятора (install success == первый green). При недоступности Telegram — healthcheck.io ping.

---

## 7. Установка в одну команду

```
curl -fsSL https://raw.githubusercontent.com/smixs/agent-second-brain/main/go.sh | bash
```

`go.sh` (как существующий `bootstrap.sh`): **скачивает себя во временный файл и re-exec с настоящим TTY** — wizard и login НИКОГДА через pipe. `trap EXIT` печатает «Установка не завершена — последний шаг: X. Запусти снова». Состояние в `~/.dbrain/install.state` (идемпотентность).

**Шаги:** root-детект → non-root юзер; `apt install git curl tmux zram-tools` + zram; `uv`+node+**пиннингованный** claude-code (`DISABLE_AUTOUPDATER=1`); wizard `.env` (4 токена + **обязательно TZ** + закомментированный `ANTHROPIC_AUTH_TOKEN`), валидация каждого; **единая `--user` модель** + verified linger; `dbrain` CLI.

### Проблема `claude login` на headless VPS (критично)

`claude auth login` предлагает ТОЛЬКО browser OAuth с redirect на `127.0.0.1` — на headless VPS не работает (телефон не достучится до localhost VPS). Это шаг, на котором умирает нетехническая установка. Текущий `setup.sh:579` вдобавок грепает `"Logged in"` (реальный вывод — JSON `loggedIn:true`) — auth-проверка уже сломана в shipped-коде.

**Решение по приоритету:**
1. **Основной — `claude setup-token`** (headless-native): инсталлятор детектит headless, печатает «открой ссылку на телефоне, одобри, вставь код». **🚩 БЛОКЕР №1: проверить, что setup-token авторизует ИНТЕРАКТИВНЫЙ подписочный путь, а не только `-p`.** Если только `-p` — премиса рушится, нужен путь 2.
2. **Fallback — login на ноутбуке + перенос креденшелов:** `claude auth login` локально → `scp ~/.claude/.credentials.json` на VPS (one-liner со скриншотом).
3. **Re-login через чат:** бот серверно запускает `setup-token`, ловит URL+код, шлёт в Telegram «пришли мне код». `/relogin` в боте + `dbrain login` в CLI.

**Проверка JSON, не грепом:** `claude auth status --json | jq -e '.loggedIn == true'`, и authoritative только end-to-end канарейка.

**Финал — `dbrain doctor` gate:** зелёный баннер «ВАШ АССИСТЕНТ ЗАПУЩЕН» печатается ТОЛЬКО если канарейка зелёная И тестовое Telegram-сообщение реально дошло.

---

## 8. Fallback (провайдер-роутинг через ANTHROPIC_BASE_URL)

**Когда:** Anthropic закрыл/реклассифицировал интерактив, ИЛИ weekly-cap стал постоянным узким местом.

**Как:** `escape-hatch.sh on` (реверсивный toggle): ставит `DBRAIN_MODE=router` + `ANTHROPIC_BASE_URL` + ключ из `~/.dbrain/escape.env`; `ask()` роутит через `claude -p` к альт-провайдеру (`-p` тут ОК — fallback, не горячий путь); `off` возвращает интерактив.

**Честно о цене:** router НЕ переиспользует подписочный OAuth (это ровно то, что Anthropic блокировал — OpenClaw/OpenCode/Goose, янв 2026). Нужен **отдельный billed API-ключ** — credential, которой у нетехнического пользователя нет. Поэтому поле застейджено в wizard, `escape-hatch.sh on` падает с точной ссылкой регистрации если ключа нет, доктор напоминает. Это **документированный degraded-режим, не бесшовный failover** — протестировать ДО 15 июня.

---

## 9. Миграция с текущего кода

**Подтверждено в коде** (ground truth):
- `processor.py`: 3 блока `subprocess.run(["claude","--print",…,"-p",prompt])` (~181, ~287, ~363), `DEFAULT_TIMEOUT=1200`, `--mcp-config` в каждом.
- `process.sh`: 4 вызова `claude --print --dangerously-skip-permissions … --mcp-config`, строки 106/131/139/163; `export TZ="${TZ:-UTC}"` (стр.24).
- `do.py:94`, `weekly.py:28`, `process.py:29`: **каждый news-up свежий `ClaudeProcessor(...)` per-request — НЕТ ни queue, ни lock, ни singleton.** Заявленная «existing single-worker serialization» НЕ существует.
- `setup.sh:579` грепает `"Logged in"` (сломано); `setup.sh:587` зовёт `claude auth login` (browser-only); бот = **system**-сервис (`/etc/systemd/system/`, `User=shima`, `multi-user.target`).

**Что переписать:**
1. **`processor.py` (EDIT):** заменить ВСЕ 3 блока на `await session.ask(prompt, timeout=DEFAULT_TIMEOUT)` к **shared singleton**. Публичные сигнатуры не менять (хендлеры не трогаем). Сохранить HTML/markdown-хелперы и загрузку skill.
2. **`do.py`/`weekly.py`/`process.py` (EDIT):** убрать per-request `ClaudeProcessor(...)`, module-level singleton + `asyncio.Lock`.
3. **`claude_session.py` (NEW):** **КРОСС-ПРОЦЕССНЫЙ flock на `~/.dbrain/pane.lock`** вокруг ВСЕГО send+await-sentinel (in-process Lock не сериализует бот против process.sh против watchdog — data corruption с первого дня). Тот же flock на `ensure_session()` (иначе TOCTOU-гонка на boot).
4. **`process.sh` → тонкий shim:** фазы больше НЕ зовут `claude -p`; каждая = `uv run python -m d_brain.claude_session ask --file .session/phaseN.txt` в `$BRAIN`. Сохранить ORIENT, graph rebuild, memory decay, git, Telegram. Триггер — systemd-таймер.
5. **`bot/main.py` (EDIT ~10 строк):** `ensure_session()` + `sd_notify`; путь logged-out → ответ пользователю.
6. **`config.py` + `.env.example`:** `dbrain_mode`, `anthropic_base_url`, `anthropic_auth_token`, `tz`, admin chat; `CLAUDE_IDLE_TIMEOUT=7200`.
7. **`setup.sh`:** auth-проверка `--json | jq`; `claude auth login` → setup-token flow; единая `--user` + verified linger; tmux+zram; doctor-gate.

**CI/install guard:** grep по ВСЕМУ репо на `--print`/` -p ` в claude-вызовах → FAIL build, если осталось вне fenced escape-hatch. Совет: **pay-as-you-go overflow ВЫКЛЮЧЕННЫМ** — утечка hard-fail, не молчаливый счёт.

---

## 10. Список файлов

**NEW:** `claude_session.py`, `watchdog.py`, `doctor.py`, `bin/dbrain`, `deploy/brain-system.md`, `deploy/dbrain-bot.service`, `deploy/dbrain-watchdog.service`, `deploy/dbrain-{doctor,process,weekly}.{timer,service}` (NO `dbrain-clear` — durable-state-first), `deploy/dbrain-notify@.service`, `deploy/tmux.conf`, `scripts/escape-hatch.sh`, `go.sh`, `vault/STATUS.md`, `vault/.session/handoff.md`.

**EDIT:** `processor.py`, `bot/handlers/{do,weekly,process}.py`, `bot/main.py`, `config.py`, `.env.example`, `setup.sh`, `process.sh`, `bot/handlers/commands.py` (+`/status /restart /heal /relogin /fix`), `vault/.claude/CLAUDE.md` (продублировать сентинел-правила), `deploy/d-brain-{process,weekly}.{service,timer}`.

**DELETE:** второй инсталлятор-путь (`install.sh` system-level дубль).

**RUNTIME (`~/.dbrain/`):** `pane.lock`, `ensure.lock`, `ready`, `inflight.lock`, `pane.log`, `heartbeat`, `brain.name`, `install.state`, `escape.env`, `watchdog.json`.

---

## 11. Риски и открытые вопросы

**Риски (приняты осознанно):**
1. **ToS-серая зона.** Митигация: рандомизация fingerprint, human-cadence rate-limiter, дисклеймер, рекомендация отдельной low-stakes подписки. Blast-radius — бан аккаунта; не устраним полностью.
2. **Weekly/5h cap — потолок, который архитектура не поднимает.** Max 20x ~300 Opus/~480 Sonnet ч/нед (+50% промо до 13 июля 2026). Дневной конвейер тяжёлый. Документировать в README (на Pro/Max-5x 24/7-бот может не влезть).
3. **Сентинел/heartbeat — soft-зависимость от модели.** Митигация: счётчик токенов + проактивный rotate, дубль в CLAUDE.md, soft-success, contract-lost состояние.
4. **Version-fragile TUI.** Пиннинг CLI + сентинел-primary + version-алерт.

**Открытые вопросы (живая проверка ДО релиза):**
1. **🚩 БЛОКЕР №1: `claude setup-token` авторизует ИНТЕРАКТИВНЫЙ подписочный путь или только `-p`?** Если только `-p` — премиса рушится, обязателен перенос креденшелов. Проверить ПЕРВЫМ.
2. Точные idle-prompt/spinner/banner/limit/logged-out строки в текущей версии — снять живым capture перед хардкодом regex.
3. Версия systemd на VPS — `RestartSteps` нужны ≥254 (Debian 11=247, 12=252, Ubuntu 22.04=249); на старых — bash-backoff.
4. `systemd-oomd` активен? — определяет, отключать ли managed-OOM для slice мозга.
5. Прерванный tool-call в JSONL при fresh-старте — идемпотентность/checkpoint side-effects (нет дублей Todoist-задач).
6. Считает ли MCP-tool-определение в idle-timeout heartbeat — влияет на `CLAUDE_IDLE_TIMEOUT`.
