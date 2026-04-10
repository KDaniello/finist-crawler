# Участие в разработке

🌐 [Read in English](../en/contributing.md)

---

## Содержание

1. Как устроен проект
2. Настройка среды разработки
3. Правила архитектуры
4. Добавление нового источника
5. Стиль кода
6. Отправка изменений

---

## 1. Как устроен проект

Перед тем как вносить изменения, прочитайте:

- docs/ru/architecture.md — архитектурные решения и границы слоёв
- .claude/CLAUDE.md — неизменяемые контракты и ключевые решения
- .claude/progress.md — текущий статус задач

Ключевое правило: **импорты строго сверху вниз**.

    core/ → engine/ → bots/ → ui/

Нижний слой не знает о верхнем. Никогда.

---

## 2. Настройка среды разработки

### Требования

    Python 3.13+
    uv (рекомендуется) или pip

### Установка

    # Клонируем репозиторий
    git clone https://github.com/your-org/finist-crawler
    cd finist-crawler

    # Создаём виртуальное окружение
    uv venv
    source .venv/bin/activate    # Linux/macOS
    .venv\Scripts\activate       # Windows

    # Устанавливаем зависимости
    uv pip install -r requirements.txt

    # Устанавливаем Camoufox (браузер)
    python -m camoufox fetch

### Запуск в режиме разработки

    python -m ui.app

### Запуск debug-бенчмарка (без UI)

    python debug_runner.py --spec reddit_comments --keyword python --pages 2

---

## 3. Правила архитектуры

### Неизменяемые контракты

Следующие интерфейсы нельзя менять без согласования,
так как они используются в нескольких слоях:

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

**JSONL запись — каждая строка файла данных**

    {
        "field1": "value",
        "external_id": "finist-xxxx",
        "message_url": "https://...",
        "metadata": {"extracted_at": "2024-01-01T00:00:00+00:00"}
    }

### Что нельзя делать

- Добавлять глобальное состояние (module-level mutable variables)
- Импортировать engine/ или bots/ из core/
- Импортировать ui/ из engine/, bots/ или core/
- Использовать fork вместо spawn для процессов
- Добавлять pandas как зависимость (только openpyxl)
- Писать в файлы логов напрямую из воркеров

### Что нужно делать

- Передавать зависимости через конструкторы (DI)
- Использовать frozen dataclass или NamedTuple для данных между процессами
- Писать логи только через logging.getLogger(__name__)
- Документировать публичные функции через docstring

---

## 4. Добавление нового источника

Подробная инструкция — в docs/ru/sources.md (раздел 8).

Краткий чеклист:

    [ ] Создан specs/my_source.yaml
    [ ] Файл проходит валидацию schema.json
    [ ] Добавлена карточка в ui/pages/launcher.py → SOURCES
    [ ] Протестирован через debug_runner.py
    [ ] Добавлена документация в docs/ru/sources.md и docs/en/sources.md

Для проверки валидности YAML:

    python -c "
    from engine.spec_loader import load_spec
    from core.config import get_paths
    spec = load_spec('my_source.yaml', get_paths().specs_dir)
    print('OK:', spec['source_key'])
    "

---

## 5. Стиль кода

Проект следует стандартному Python стилю с несколькими правилами:

### Форматирование

    Форматтер:  ruff format (или black)
    Линтер:     ruff check
    Длина строки: 100 символов

### Типизация

Все публичные функции и методы должны иметь аннотации типов:

    # Правильно
    def save_batch(self, data: Iterable[dict[str, Any]]) -> None:

    # Неправильно
    def save_batch(self, data):

### Именование

    Классы:        PascalCase   (DataWriter, TokenBucket)
    Функции:       snake_case   (build_plan, get_settings)
    Константы:     UPPER_SNAKE  (LEAN_PREFS, MAX_COL_WIDTH)
    Приватные:     _underscore  (_extract_cursor, _refill)

### Исключения

Используйте иерархию исключений проекта (core/exceptions.py):

    raise CaptchaBlockError(url=url, detail="403 Forbidden")
    raise NetworkError(f"Таймаут на {url}")
    raise ConfigurationError(f"Нет параметра keyword")

---

## 6. Отправка изменений

### Ветки

    main        — стабильная версия (только через PR)
    dev         — текущая разработка
    feature/*   — новые функции
    fix/*       — исправления

### Коммиты

Используйте префиксы:

    feat:   новая функциональность
    fix:    исправление бага
    docs:   документация
    refactor: рефакторинг без изменения поведения
    test:   тесты
    chore:  служебные изменения (зависимости, CI)

Примеры:

    feat: add Wildberries reviews parser (specs/wb_reviews.yaml)
    fix: handle empty cursor in Steam paginator
    docs: add data_formats.md in Russian and English
    refactor: extract _branch_name() from MonitorPage

### Pull Request

Перед созданием PR убедитесь:

    [ ] Код проходит ruff check без ошибок
    [ ] Новый источник протестирован на реальных данных
    [ ] Документация обновлена (ru + en)
    [ ] Контракты IExecutor и WorkerCallable не нарушены
    [ ] Импорты соответствуют правилу core → engine → bots → ui