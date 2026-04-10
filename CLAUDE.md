# Finist Crawler — Обзор проекта

Этот файл даёт быстрый контекст о проекте для новых участников,
ИИ-ассистентов и всех, кто хочет разобраться в коде.

---

## Что делает проект

Десктопное приложение для сбора текстовых данных из открытых источников:
Reddit, 2GIS, Steam, Хабр, Лента.ру, Отзовик.

Пользователь выбирает источник, вводит ключевое слово или URL,
получает структурированный файл Excel или CSV.

---

## Стек технологий

    Python 3.13
    Flet            — десктопный UI (Flutter под капотом)
    curl_cffi       — HTTP с TLS-маскировкой под Chrome
    Camoufox        — антидетект браузер на базе Firefox + Playwright
    BeautifulSoup4  — парсинг HTML
    JMESPath        — извлечение данных из JSON
    pydantic-settings — конфигурация
    openpyxl        — экспорт в Excel (без pandas)
    multiprocessing — изоляция воркеров (spawn, не fork)

---

## Структура проекта

    core/       Ядро: конфиг, логгер, файлы, диспетчер, исключения
    engine/     Движок: загрузка спеков, парсинг, rate limiter, executors
    bots/       Точка входа воркера (run_universal_bot)
    ui/         Flet интерфейс: launcher, monitor, results
    specs/      YAML спецификации источников (без Python-кода)
    assets/     Шрифты, иконка
    scripts/    Вспомогательные скрипты (проверка шрифтов, иконка)
    docs/       Документация (ru/ и en/)

---

## Архитектурное правило №1

Импорты строго сверху вниз:

    core → engine → bots → ui

Нижний слой не знает о верхнем. Никогда.
Нарушение этого правила — архитектурная ошибка.

---

## Как добавить новый источник

Создать файл specs/my_source.yaml — Python-код не нужен.
Инструкция: docs/ru/sources.md, раздел 8.

---

## Как запустить локально

    # Установка зависимостей
    pip install -r requirements.txt

    # Установка браузера Camoufox
    python -m camoufox fetch

    # Проверка шрифтов
    python scripts/download_fonts.py

    # Запуск
    python main.py

---

## Как собрать .exe

    pip install pyinstaller
    python scripts/generate_icon.py
    pyinstaller finist.spec
    # Результат: dist/FinistCrawler.exe

---

## Ключевые файлы для понимания кода

    core/dispatcher.py        — как запускаются воркеры
    engine/fallback_chain.py  — как переключается curl_cffi → браузер
    engine/parsing_rules.py   — как работает парсинг HTML/JSON
    bots/universal_bot.py     — точка входа каждого воркера
    ui/app.py                 — AppController, навигация

---

## Документация

    docs/ru/architecture.md   — архитектура и принципы
    docs/ru/data_formats.md   — форматы данных по каждому источнику
    docs/ru/sources.md        — описание источников и добавление новых
    docs/ru/ethics.md         — этика использования
    docs/ru/contributing.md   — правила разработки

    docs/en/                  — то же на английском

---

## Лицензия

MIT — см. файл LICENSE.