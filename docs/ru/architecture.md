# Архитектура Finist Crawler

🌐 [Read in English](../en/architecture.md)

---

## Содержание

1. Принципы проектирования
2. Схема компонентов
3. Слои и границы
4. Жизненный цикл запроса
5. Мультипроцессная модель
6. Цепочка Fallback
7. Хранение данных
8. Поток импортов

---

## 1. Принципы проектирования

Finist Crawler строится на трёх ключевых принципах.

**Zero Infrastructure.**
Приложение не требует установки баз данных, брокеров очередей или
внешних серверов. Все компоненты работают в одном процессе ОС (главный
процесс) или порождаются им напрямую (воркеры). Пользователь скачивает
один исполняемый файл и сразу начинает работу.

**Dependency Injection без фреймворка.**
Зависимости передаются явно через конструкторы и аргументы функций.
Ни один модуль не импортирует глобальное состояние из другого.
Это делает каждый компонент тестируемым изолированно.

**Однонаправленный поток данных.**
Импорты строго сверху вниз: core → engine → bots → ui.
Нижние слои не знают о верхних. Нарушение этого порядка
является архитектурной ошибкой и должно быть исправлено немедленно.

---

## 2. Схема компонентов

    ┌─────────────────────────────────────────────┐
    │                   UI (Flet)                 │
    │  LauncherPage  MonitorPage  ResultsPage      │
    └──────────────────────┬──────────────────────┘
                           │
                    AppController
                           │
             ┌─────────────┴──────────────┐
             │                            │
        Dispatcher                  SystemMonitor
    (multiprocessing)             (psutil, CPU/RAM)
             │
     ┌───────┴────────┐
     │                │
  Worker-A         Worker-B          (отдельные процессы ОС)
     │
  run_universal_bot()
     │
  load_spec() → build_plan() → FallbackOrchestrator
                                      │
                          ┌───────────┴───────────┐
                          │                       │
                   LightExecutor           StealthExecutor
                   (curl_cffi)             (Camoufox/Playwright)
                          │                       │
                    parse_page()            page.content()
                          │                       │
                       DataWriter (JSONL на диске)

---

## 3. Слои и границы

### core/
Ядро системы. Не знает ни о чём выше себя.

    config.py        — пути, настройки (pydantic-settings)
    dispatcher.py    — запуск и остановка воркеров (spawn)
    file_manager.py  — сессии, запись JSONL, экспорт CSV/XLSX
    job_config.py    — типизированная конфигурация задачи
    logger.py        — QueueHandler + QueueListener, Discord
    resources.py     — мониторинг CPU/RAM (psutil)
    telemetry.py     — типизированные события от воркеров
    exceptions.py    — иерархия исключений проекта
    updater.py       — OTA обновление YAML спецификаций

### engine/
Движок парсинга. Знает о core, не знает о bots и ui.

    spec_loader.py      — загрузка и валидация YAML (jsonschema)
    parsing_rules.py    — CrawlerPlan, build_plan(), parse_page()
    rate_limiter.py     — TokenBucket, адаптивное замедление
    fallback_chain.py   — FallbackOrchestrator (Light → Stealth)
    executors/light.py  — curl_cffi, TLS fingerprint, async
    executors/stealth.py — Camoufox, Playwright, browser_lock
    browser/            — ImmortalBrowser, HumanBehavior, ProfileManager

### bots/
Точка входа воркера. Знает о core и engine.

    universal_bot.py — run_universal_bot() — функция-воркер

### ui/
Интерфейс. Знает о core. Не вызывает engine напрямую.

    app.py           — AppController, main(), навигация
    theme.py         — ColorTokens, ThemeController
    pages/launcher.py — выбор источника, запуск
    pages/monitor.py  — мониторинг, телеметрия, логи
    pages/results.py  — список сессий, экспорт, предпросмотр

### specs/
YAML-спецификации источников. Не являются Python-кодом.
Добавление нового источника — это создание нового YAML файла
без правки кода движка.

---

## 4. Жизненный цикл запроса

Ниже показан путь от клика пользователя до записи на диск.

    1. Пользователь выбирает источник и нажимает «Начать парсинг»
       └─ LauncherPage._on_start()

    2. UI создаёт JobConfig и передаёт его AppController
       └─ AppController.start_parsing([job_config])

    3. Диспетчер создаёт сессию и порождает процесс-воркер
       └─ Dispatcher.start_tasks(run_universal_bot, specs, overrides)
       └─ SessionManager.create_session() → "session_2024-01-01_12-00-00"
       └─ ctx.Process(target=run_universal_bot, ...).start()

    4. Воркер настраивает логирование и запускает async-цикл
       └─ setup_worker_logging(log_queue)
       └─ asyncio.run(_async_run())

    5. Движок строит план и запускает оркестратор
       └─ load_spec("reddit_comments.yaml", specs_dir)
       └─ build_plan(spec_data, config_overrides) → CrawlerPlan
       └─ FallbackOrchestrator.execute_plan(plan, save_cb)

    6. LightExecutor обходит страницы
       └─ curl_cffi.AsyncSession.get(url)
       └─ parse_page(html, plan, url, phase) → records
       └─ save_cb(records) → DataWriter.save_batch()
       └─ Запись в JSONL (атомарная дозапись)

    7. Телеметрия идёт в лог-очередь главного процесса
       └─ logger.info("TELEMETRY|PROGRESS|url|current|total")
       └─ QueueHandler → multiprocessing.Queue → QueueListener
       └─ UILogHandler.emit() → MonitorPage._apply_telemetry()

    8. Воркер завершается, Dispatcher фиксирует exitcode
       └─ proc.exitcode == 0 → успех

---

## 5. Мультипроцессная модель

Finist использует контекст **spawn** (не fork) для всех платформ.

Причины:
- fork ломает asyncio-петлю в дочернем процессе на macOS (Python 3.12+)
- fork несовместим с PyInstaller (frozen-приложение)
- spawn гарантирует чистое состояние каждого воркера

Каждый источник данных запускается в **отдельном процессе**.
Это означает:
- Краш воркера Reddit не влияет на воркер 2GIS
- Браузер Camoufox поднимается в изолированном процессе
- browser_lock (multiprocessing.Lock) не даёт двум воркерам
  одновременно поднять тяжёлый браузер

Лог-очередь (multiprocessing.Queue) — единственный канал связи
между воркерами и главным процессом. Воркеры не пишут в файлы
логов напрямую — они кладут записи в очередь, QueueListener
в главном процессе физически пишет в файл.

---

## 6. Цепочка Fallback

FallbackOrchestrator реализует паттерн «Цепочка ответственности».

    Стратегия "static":
        LightExecutor → (CaptchaBlockError) → ошибка, стоп

    Стратегия "browser":
        StealthExecutor (сразу, без попытки curl_cffi)

    Стратегия "auto" (по умолчанию):
        LightExecutor
            → успех: готово
            → CaptchaBlockError / NetworkError: StealthExecutor
                → успех: готово
                → ошибка: NetworkError (критический сбой)

Когда срабатывает Fallback:
- HTTP 403 Forbidden
- HTTP 503 Service Unavailable
- Обнаружен Cloudflare Turnstile / ReCaptcha / hCaptcha в HTML
- Маркер "just a moment" или "verify you are human" в заголовке страницы

StealthExecutor захватывает browser_lock перед запуском браузера.
Это системный Mutex: в любой момент времени работает не более
одного экземпляра Camoufox на всё приложение.

---

## 7. Хранение данных

    data/
    ├── session_2024-01-01_12-00-00-123456/
    │   ├── reddit_discussions/
    │   │   ├── reddit_discussions.jsonl      ← сырые данные
    │   │   └── reddit_discussions_export.xlsx ← после экспорта
    │   └── twogis_reviews/
    │       ├── twogis_reviews.jsonl
    │       └── twogis_reviews_export.csv
    └── profiles/
        └── www.reddit.com/
            └── <session_id>/
                └── state.json                ← стейт браузерного профиля

**JSONL** (JSON Lines) выбран по трём причинам:
1. Атомарная дозапись (append): краш воркера не портит уже записанные строки
2. Нет блокировок между процессами (каждый воркер пишет в свой файл)
3. Легко читается построчно при экспорте (не нужно загружать весь файл)

Экспорт в XLSX реализован через openpyxl напрямую, без pandas.
Это снижает размер дистрибутива на ~30 MB и ускоряет запуск на слабых ПК.

---

## 8. Поток импортов

Правило: каждый слой знает только о слое ниже.

    core/       — не импортирует ничего из проекта
    engine/     — импортирует только из core/
    bots/       — импортирует из core/ и engine/
    ui/         — импортирует только из core/

Если ui/ начинает импортировать из engine/ напрямую —
это нарушение архитектуры. UI должен общаться с движком
только через AppController и JobConfig.

Проверка при добавлении нового кода:

    Вопрос: «Какой слой я пишу?»
    Вопрос: «Что я импортирую?»
    Если импорт идёт «вверх по стеку» — это ошибка.