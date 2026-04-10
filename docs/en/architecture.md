# Finist Crawler — Architecture

🌐 [Читать на русском](../ru/architecture.md)

---

## Contents

1. Design principles
2. Component diagram
3. Layers and boundaries
4. Request lifecycle
5. Multiprocessing model
6. Fallback chain
7. Data storage
8. Import flow

---

## 1. Design principles

Finist Crawler is built on three core principles.

**Zero Infrastructure.**
The application requires no databases, message brokers, or external servers.
All components run inside a single OS process (the main process) or are
spawned directly from it (workers). The user downloads one executable
and starts working immediately.

**Dependency Injection without a framework.**
Dependencies are passed explicitly through constructors and function arguments.
No module imports global state from another. This makes every component
independently testable.

**Unidirectional data flow.**
Imports are strictly top-down: core → engine → bots → ui.
Lower layers have no knowledge of upper layers. Violating this order
is an architectural error that must be corrected immediately.

---

## 2. Component diagram

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
  Worker-A         Worker-B          (separate OS processes)
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
                       DataWriter (JSONL on disk)

---

## 3. Layers and boundaries

### core/
The system kernel. Has no knowledge of anything above it.

    config.py        — paths, settings (pydantic-settings)
    dispatcher.py    — worker process start/stop (spawn)
    file_manager.py  — sessions, JSONL writing, CSV/XLSX export
    job_config.py    — typed task configuration
    logger.py        — QueueHandler + QueueListener, Discord
    resources.py     — CPU/RAM monitoring (psutil)
    telemetry.py     — typed events from workers
    exceptions.py    — project exception hierarchy
    updater.py       — OTA update of YAML specifications

### engine/
The parsing engine. Knows about core, has no knowledge of bots or ui.

    spec_loader.py      — YAML loading and validation (jsonschema)
    parsing_rules.py    — CrawlerPlan, build_plan(), parse_page()
    rate_limiter.py     — TokenBucket, adaptive slowdown
    fallback_chain.py   — FallbackOrchestrator (Light → Stealth)
    executors/light.py  — curl_cffi, TLS fingerprint, async
    executors/stealth.py — Camoufox, Playwright, browser_lock
    browser/            — ImmortalBrowser, HumanBehavior, ProfileManager

### bots/
Worker entry point. Knows about core and engine.

    universal_bot.py — run_universal_bot() — the worker function

### ui/
The interface. Knows about core. Does not call engine directly.

    app.py           — AppController, main(), navigation
    theme.py         — ColorTokens, ThemeController
    pages/launcher.py — source selection, launch
    pages/monitor.py  — monitoring, telemetry, logs
    pages/results.py  — session list, export, preview

### specs/
YAML source specifications. Not Python code.
Adding a new source means creating a new YAML file
without touching the engine code.

---

## 4. Request lifecycle

The path from a user click to a record written on disk.

    1. User selects a source and clicks "Start crawling"
       └─ LauncherPage._on_start()

    2. UI creates a JobConfig and passes it to AppController
       └─ AppController.start_parsing([job_config])

    3. Dispatcher creates a session and spawns a worker process
       └─ Dispatcher.start_tasks(run_universal_bot, specs, overrides)
       └─ SessionManager.create_session() → "session_2024-01-01_12-00-00"
       └─ ctx.Process(target=run_universal_bot, ...).start()

    4. Worker configures logging and starts the async loop
       └─ setup_worker_logging(log_queue)
       └─ asyncio.run(_async_run())

    5. Engine builds the plan and launches the orchestrator
       └─ load_spec("reddit_comments.yaml", specs_dir)
       └─ build_plan(spec_data, config_overrides) → CrawlerPlan
       └─ FallbackOrchestrator.execute_plan(plan, save_cb)

    6. LightExecutor crawls pages
       └─ curl_cffi.AsyncSession.get(url)
       └─ parse_page(html, plan, url, phase) → records
       └─ save_cb(records) → DataWriter.save_batch()
       └─ Written to JSONL (atomic append)

    7. Telemetry flows to the main process log queue
       └─ logger.info("TELEMETRY|PROGRESS|url|current|total")
       └─ QueueHandler → multiprocessing.Queue → QueueListener
       └─ UILogHandler.emit() → MonitorPage._apply_telemetry()

    8. Worker exits, Dispatcher records the exitcode
       └─ proc.exitcode == 0 → success

---

## 5. Multiprocessing model

Finist uses the **spawn** context (not fork) on all platforms.

Reasons:
- fork breaks the asyncio event loop in child processes on macOS (Python 3.12+)
- fork is incompatible with PyInstaller (frozen application)
- spawn guarantees a clean state for each worker

Each data source runs in a **separate OS process**. This means:
- A crash in the Reddit worker does not affect the 2GIS worker
- Camoufox launches in an isolated process
- browser_lock (multiprocessing.Lock) prevents two workers from
  launching a heavy browser simultaneously

The log queue (multiprocessing.Queue) is the only communication channel
between workers and the main process. Workers never write to log files
directly — they put records into the queue, and the QueueListener
in the main process physically writes to the file.

---

## 6. Fallback chain

FallbackOrchestrator implements the Chain of Responsibility pattern.

    Strategy "static":
        LightExecutor → (CaptchaBlockError) → error, stop

    Strategy "browser":
        StealthExecutor (immediately, no curl_cffi attempt)

    Strategy "auto" (default):
        LightExecutor
            → success: done
            → CaptchaBlockError / NetworkError: StealthExecutor
                → success: done
                → error: NetworkError (critical failure)

Fallback triggers when:
- HTTP 403 Forbidden
- HTTP 503 Service Unavailable
- Cloudflare Turnstile / ReCaptcha / hCaptcha detected in HTML
- "just a moment" or "verify you are human" found in the page title

StealthExecutor acquires browser_lock before launching the browser.
This is a system Mutex: at any given moment, at most one Camoufox
instance is running across the entire application.

---

## 7. Data storage

    data/
    ├── session_2024-01-01_12-00-00-123456/
    │   ├── reddit_discussions/
    │   │   ├── reddit_discussions.jsonl       ← raw data
    │   │   └── reddit_discussions_export.xlsx ← after export
    │   └── twogis_reviews/
    │       ├── twogis_reviews.jsonl
    │       └── twogis_reviews_export.csv
    └── profiles/
        └── www.reddit.com/
            └── <session_id>/
                └── state.json                 ← browser profile state

**JSONL** (JSON Lines) was chosen for three reasons:
1. Atomic append: a worker crash does not corrupt already-written lines
2. No cross-process locking (each worker writes to its own file)
3. Simple line-by-line reading during export (no need to load the whole file)

XLSX export is implemented directly via openpyxl, without pandas.
This reduces the distribution size by ~30 MB and speeds up launch on weak hardware.

---

## 8. Import flow

Rule: each layer only knows about the layer directly below it.

    core/       — imports nothing from the project
    engine/     — imports only from core/
    bots/       — imports from core/ and engine/
    ui/         — imports only from core/

If ui/ starts importing from engine/ directly —
that is an architectural violation. The UI must communicate
with the engine only through AppController and JobConfig.

Checklist when adding new code:

    Question: "Which layer am I writing?"
    Question: "What am I importing?"
    If the import goes "up the stack" — it is an error.