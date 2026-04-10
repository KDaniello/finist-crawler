# Contributing

🌐 [Читать на русском](../ru/contributing.md)

---

## Contents

1. Project structure
2. Setting up the development environment
3. Architecture rules
4. Adding a new source
5. Code style
6. Submitting changes

---

## 1. Project structure

Before making changes, please read:

- docs/en/architecture.md — architectural decisions and layer boundaries
- .claude/CLAUDE.md — immutable contracts and key decisions
- .claude/progress.md — current task status

Core rule: **imports are strictly top-down**.

    core/ → engine/ → bots/ → ui/

A lower layer never knows about an upper layer. Never.

---

## 2. Setting up the development environment

### Requirements

    Python 3.13+
    uv (recommended) or pip

### Installation

    # Clone the repository
    git clone https://github.com/your-org/finist-crawler
    cd finist-crawler

    # Create a virtual environment
    uv venv
    source .venv/bin/activate    # Linux/macOS
    .venv\Scripts\activate       # Windows

    # Install dependencies
    uv pip install -r requirements.txt

    # Install Camoufox (browser)
    python -m camoufox fetch

### Running in development mode

    python -m ui.app

### Running the debug benchmark (without UI)

    python debug_runner.py --spec reddit_comments --keyword python --pages 2

---

## 3. Architecture rules

### Immutable contracts

The following interfaces must not be changed without discussion,
as they are used across multiple layers:

**IExecutor.execute() — engine/executors/base.py**

    async def execute(
        plan: CrawlerPlan,
        save_cb: SaveCallback,
        proxy_url: str | None = None,
    ) -> tuple[int, ExecutorStats]: ...

**WorkerCallable — core/dispatcher.py**

    def __call__(
        spec_name: str,
        session_id: str,
        config_overrides: dict[str, Any],
        log_queue: multiprocessing.Queue,
        browser_lock: LockType,
    ) -> None: ...

**JSONL record — each line of a data file**

    {
        "field1": "value",
        "external_id": "finist-xxxx",
        "message_url": "https://...",
        "metadata": {"extracted_at": "2024-01-01T00:00:00+00:00"}
    }

### What is not allowed

- Adding global state (module-level mutable variables)
- Importing engine/ or bots/ from core/
- Importing ui/ from engine/, bots/, or core/
- Using fork instead of spawn for processes
- Adding pandas as a dependency (openpyxl only)
- Writing to log files directly from workers

### What is required

- Pass dependencies through constructors (DI)
- Use frozen dataclass or NamedTuple for data passed between processes
- Write logs only via logging.getLogger(__name__)
- Document public functions with docstrings

---

## 4. Adding a new source

Detailed instructions — in docs/en/sources.md (section 8).

Quick checklist:

    [ ] specs/my_source.yaml created
    [ ] File passes schema.json validation
    [ ] Card added to ui/pages/launcher.py → SOURCES
    [ ] Tested via debug_runner.py with real data
    [ ] Documentation updated in docs/ru/sources.md and docs/en/sources.md

To verify YAML validity:

    python -c "
    from engine.spec_loader import load_spec
    from core.config import get_paths
    spec = load_spec('my_source.yaml', get_paths().specs_dir)
    print('OK:', spec['source_key'])
    "

---

## 5. Code style

The project follows standard Python style with a few additional rules.

### Formatting

    Formatter:   ruff format (or black)
    Linter:      ruff check
    Line length: 100 characters

### Type annotations

All public functions and methods must have type annotations:

    # Correct
    def save_batch(self, data: Iterable[dict[str, Any]]) -> None:

    # Incorrect
    def save_batch(self, data):

### Naming

    Classes:     PascalCase   (DataWriter, TokenBucket)
    Functions:   snake_case   (build_plan, get_settings)
    Constants:   UPPER_SNAKE  (LEAN_PREFS, MAX_COL_WIDTH)
    Private:     _underscore  (_extract_cursor, _refill)

### Exceptions

Use the project exception hierarchy (core/exceptions.py):

    raise CaptchaBlockError(url=url, detail="403 Forbidden")
    raise NetworkError(f"Timeout on {url}")
    raise ConfigurationError(f"Missing parameter: keyword")

---

## 6. Submitting changes

### Branches

    main        — stable version (PRs only)
    dev         — active development
    feature/*   — new features
    fix/*       — bug fixes

### Commits

Use prefixes:

    feat:     new functionality
    fix:      bug fix
    docs:     documentation
    refactor: refactoring without behaviour changes
    test:     tests
    chore:    housekeeping (dependencies, CI)

Examples:

    feat: add Wildberries reviews parser (specs/wb_reviews.yaml)
    fix: handle empty cursor in Steam paginator
    docs: add data_formats.md in Russian and English
    refactor: extract _branch_name() from MonitorPage

### Pull Request checklist

Before opening a PR, verify:

    [ ] Code passes ruff check with no errors
    [ ] New source tested on real data
    [ ] Documentation updated (ru + en)
    [ ] IExecutor and WorkerCallable contracts not violated
    [ ] Imports comply with the core → engine → bots → ui rule