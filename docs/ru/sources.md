# Поддерживаемые источники

🌐 [Read in English](../en/sources.md)

---

## Содержание

1. Обзор
2. Reddit
3. 2GIS
4. Steam
5. Хабр
6. Лента.ру
7. Отзовик
8. Добавление нового источника

---

## 1. Обзор

| Источник  | Метод            | Скорость    | Стратегия      | Параметр           |
|-----------|------------------|-------------|----------------|--------------------|
| Reddit    | API (curl_cffi)  | 57 зап/с    | auto (List→Detail) | keyword        |
| 2GIS      | API (curl_cffi)  | 52 зап/с    | static (List→Detail) | keyword      |
| Steam     | API (curl_cffi)  | 20 зап/с    | static (Detail only) | app_id      |
| Хабр      | API (curl_cffi)  | 1.4 зап/с   | static (List→Detail) | keyword      |
| Лента.ру  | API (curl_cffi)  | 1.2 зап/с   | static (List→Detail) | keyword      |
| Отзовик   | Браузер          | ~0.3 зап/с  | browser (List→Detail) | direct_url  |

---

## 2. Reddit

**Файл спецификации:** reddit_comments.yaml
**Стратегия:** auto (curl_cffi → Camoufox при блокировке)
**Поток данных:** List (поиск постов) → Detail (комментарии к каждому посту)

### Как это работает

1. Запрос к Search API:
   https://www.reddit.com/r/all/search.json?q={keyword}&type=link&limit=100
2. Из результатов извлекаются permalink'и постов
3. Для каждого поста: запрос к https://www.reddit.com{permalink}.json
4. Рекурсивное извлечение комментариев (включая вложенные ответы)

### Параметры

    keyword        Поисковый запрос (например: "chatgpt", "python")
    max_pages      Страниц поиска (каждая = 100 постов)
    detail_max_pages  Не используется (все комментарии поста за 1 запрос)

### Ограничения

- Reddit не требует OAuth для базового поиска
- User-Agent должен выглядеть как бот (FinistCrawlerBot/2.0)
- Прогрев сессии через главную страницу Reddit помогает избежать 429
- При блокировке автоматически активируется Camoufox

---

## 3. 2GIS

**Файл спецификации:** twogis_search.yaml
**Стратегия:** static (только curl_cffi)
**Поток данных:** List (HTML поиск организаций) → Detail (JSON API отзывов)

### Как это работает

1. Парсинг HTML страницы поиска: https://2gis.ru/moscow/search/{keyword}/page/1
2. Из ссылок вида /moscow/firm/4504127908559765 извлекается числовой ID
3. Для каждого ID: запросы к открытому API отзывов:
   https://public-api.reviews.2gis.com/3.0/branches/{id}/reviews?limit=50&offset=0&...
4. Пагинация через offset (0, 50, 100...)

### Параметры

    keyword        Название организации или тип заведения
    max_pages      Страниц поиска организаций
    detail_max_pages  Страниц отзывов на организацию (0 = все)

### Ограничения

- API отзывов открытый, ключ в URL публичный
- Поиск ограничен Москвой (в URL /moscow/) — это можно изменить в YAML
- Скорость высокая (52 зап/с) т.к. API не имеет жёсткого rate limiting

---

## 4. Steam

**Файл спецификации:** steam_reviews.yaml
**Стратегия:** static (только curl_cffi)
**Поток данных:** Detail only (прямые запросы к API отзывов)

### Как это работает

1. Прямой запрос к API отзывов Steam:
   https://store.steampowered.com/appreviews/{app_id}?json=1&filter=recent&language=all&num_per_page=50&cursor=*
2. Пагинация через cursor (значение приходит в теле ответа)
3. Конец данных: cursor не изменился или reviews пустой

### Как найти App ID

В URL страницы игры: https://store.steampowered.com/app/1091500/Cyberpunk_2077/
App ID = 1091500

### Параметры

    app_id            Числовой ID игры из URL Steam
    detail_max_pages  Страниц отзывов (каждая = 50 отзывов, 0 = все)

### Ограничения

- API полностью публичный, без авторизации
- Параметр language=all собирает отзывы на всех языках
- Параметр filter=recent — сортировка по дате (можно изменить на helpful)
- Поле language в каждой записи позволяет фильтровать после сбора

---

## 5. Хабр

**Файл спецификации:** habr_search.yaml
**Стратегия:** static (только curl_cffi)
**Поток данных:** List (Search API) → Detail (API статьи)

### Как это работает

1. Запрос к Search API:
   https://habr.com/kek/v2/articles/?query={keyword}&order=relevance&fl=ru&hl=ru&page=1&perPage=20
2. Из publicationRefs извлекаются числовые ID статей
3. Для каждого ID: https://habr.com/kek/v2/articles/{id}/?fl=ru&hl=ru
4. Извлекаются: заголовок, автор, дата, статистика, полный HTML текста

### Параметры

    keyword        Поисковый запрос (например: "Python", "машинное обучение")
    max_pages      Страниц Search API (каждая = 20 статей)

### Ограничения

- Внутренний API /kek/v2/ — не официальный, может измениться
- Скорость: ~1.4 зап/с (двойной запрос на статью)
- Статьи фильтруются по языку: fl=ru (только русские)
- Поле text содержит HTML-разметку, требует обработки для анализа

---

## 6. Лента.ру

**Файл спецификации:** lenta_search.yaml
**Стратегия:** static (только curl_cffi)
**Поток данных:** List (Search API v2) → Detail (HTML статьи)

### Как это работает

1. Запрос к Search API v2:
   https://lenta.ru/search/v2/process?query={keyword}&from=0&size=10&sort=2&title_only=0&domain=1
2. Из массива matches извлекаются URL и метаданные статей
3. Нетекстовые типы пропускаются (галереи, видео, онлайны)
4. Для каждой статьи: загрузка HTML → извлечение из <script class="json-topic-info">
5. При отсутствии json-topic-info — fallback на CSS-селекторы

### Параметры

    keyword        Поисковый запрос
    max_pages      Страниц Search API (каждая = 10 статей)

### Ограничения

- API возвращает максимум 10 000 результатов (from= <= 9990)
- Параметр sort=2 — сортировка по релевантности
- Полный текст доступен только через HTML страницы (не через API)
- Скорость: ~1.2 зап/с (двойной запрос на статью)

---

## 7. Отзовик

**Файл спецификации:** otzovik_reviews.yaml
**Стратегия:** browser (только Camoufox)
**Поток данных:** List (HTML список отзывов) → Detail (HTML страница отзыва)

### Как это работает

1. Открытие браузера Camoufox (Firefox с антидетект-патчами)
2. Загрузка страницы: https://otzovik.com/reviews/{keyword}/
3. Если обнаружена Яндекс SmartCaptcha — показывается таймер 300 сек
4. Пользователь решает капчу в открытом браузере
5. Извлечение ссылок на отзывы, переход на каждую страницу
6. Сохранение HTML, парсинг через BeautifulSoup

### Параметры

    direct_url     Полный URL страницы отзывов на Отзовике
                   Пример: https://otzovik.com/reviews/kinopoisk_ru-onlayn-kinoteatr/
    max_pages      Страниц списка отзывов

### Ограничения

- Требует визуального браузера (не headless)
- Яндекс SmartCaptcha появляется практически всегда
- Скорость сильно зависит от скорости загрузки страниц
- Потребление RAM: 800–1400 MB из-за браузера

---

## 8. Добавление нового источника

Finist Crawler поддерживает добавление новых источников через YAML без правки Python-кода.

### Шаги

1. Создайте файл specs/my_source.yaml
2. Укажите обязательные поля: source_key, version, flow
3. Настройте crawler.list и/или crawler.detail
4. Выберите extraction_mode: html, json, или кастомный

### Доступные режимы извлечения

    html          BeautifulSoup + CSS-селекторы
    json          JMESPath выражения
    reddit        Специальный рекурсивный Reddit-парсер
    steam         Специальный Steam cursor-парсер
    lenta_search  Специальный Lenta.ru Search API парсер
    lenta_article Специальный Lenta.ru HTML парсер

### Минимальный шаблон (HTML источник)

    source_key: my_reviews
    version: v1
    description: Мой новый источник
    flow: [list, detail]

    crawler:
      render: static
      request_headers:
        User-Agent: "Mozilla/5.0 ..."

      limits:
        max_pages: 5
        concurrency: 3
        requests_per_second: 2.0

      list:
        url_template: "https://example.com/reviews/{keyword}"
        extraction_mode: html
        item_selector: ".review-item"
        fields:
          detail_url:
            selector: "a.read-more"
            attr: "href"
        next_page:
          selector: "a.next-page"
          attr: "href"

      detail:
        url_template: "https://example.com{}"
        extraction_mode: html
        item_selector: "body"
        fields:
          text:
            selector: ".review-text"
          author:
            selector: ".author-name"
          rating:
            selector: ".stars"
            attr: "data-value"

5. Перезапустите приложение. Новый источник появится в списке, если вы добавите его карточку в ui/pages/launcher.py в список SOURCES.