# Contributing to Finist Crawler

Спасибо за интерес к проекту!

## Сообщить об ошибке

Откройте [Issue](../../issues/new) и опишите:
- Что вы делали
- Что ожидали увидеть
- Что произошло на самом деле
- Версию Windows и Python

## Предложить улучшение

Откройте [Issue](../../issues/new) с тегом `enhancement`.

## Отправить Pull Request

1. Форкните репозиторий
2. Создайте ветку: `git checkout -b feature/my-feature`
3. Прочитайте [docs/ru/contributing.md](docs/ru/contributing.md) —
   там архитектурные правила и стиль кода
4. Убедитесь что `ruff check .` проходит без ошибок
5. Создайте PR в ветку `dev`

## Добавить новый источник данных

Инструкция в [docs/ru/sources.md](docs/ru/sources.md) — раздел 8.
Новый источник = новый YAML файл в `specs/`, Python-код не нужен.