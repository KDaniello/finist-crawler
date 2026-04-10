# Supported Sources

🌐 [Читать на русском](../ru/sources.md)

---

## Contents

1. Overview
2. Reddit
3. 2GIS
4. Steam
5. Habr
6. Lenta.ru
7. Otzovik
8. Adding a new source

---

## 1. Overview

| Source    | Method           | Speed       | Strategy            | Parameter   |
|-----------|------------------|-------------|---------------------|-------------|
| Reddit    | API (curl_cffi)  | 57 rec/s    | auto (List→Detail)  | keyword     |
| 2GIS      | API (curl_cffi)  | 52 rec/s    | static (List→Detail)| keyword     |
| Steam     | API (curl_cffi)  | 20 rec/s    | static (Detail only)| app_id      |
| Habr      | API (curl_cffi)  | 1.4 rec/s   | static (List→Detail)| keyword     |
| Lenta.ru  | API (curl_cffi)  | 1.2 rec/s   | static (List→Detail)| keyword     |
| Otzovik   | Browser          | ~0.3 rec/s  | browser (List→Detail)| direct_url |

---

## 2. Reddit

**Spec file:** reddit_comments.yaml
**Strategy:** auto (curl_cffi → Camoufox on block)
**Data flow:** List (post search) → Detail (comments per post)

### How it works

1. Request to the Search API:
   https://www.reddit.com/r/all/search.json?q={keyword}&type=link&limit=100
2. Post permalinks are extracted from results
3. For each post: https://www.reddit.com{permalink}.json
4. Comments are extracted recursively (including nested replies)

### Parameters

    keyword           Search query (e.g. "chatgpt", "python")
    max_pages         Search result pages (each = 100 posts)
    detail_max_pages  Not used (all post comments fetched in 1 request)

### Limitations

- Reddit does not require OAuth for basic search
- User-Agent must look like a bot (FinistCrawlerBot/2.0)
- Session warm-up via the Reddit homepage helps avoid 429
- Camoufox activates automatically on block

---

## 3. 2GIS

**Spec file:** twogis_search.yaml
**Strategy:** static (curl_cffi only)
**Data flow:** List (HTML business search) → Detail (JSON reviews API)

### How it works

1. HTML search page parsing: https://2gis.ru/moscow/search/{keyword}/page/1
2. Numeric business ID extracted from links like /moscow/firm/4504127908559765
3. For each ID: open reviews API requests:
   https://public-api.reviews.2gis.com/3.0/branches/{id}/reviews?limit=50&offset=0&...
4. Pagination via offset (0, 50, 100...)

### Parameters

    keyword           Business name or establishment type
    max_pages         Business search pages
    detail_max_pages  Review pages per business (0 = all)

### Limitations

- The reviews API is open; the key in the URL is public
- Search is scoped to Moscow (/moscow/ in the URL) — editable in YAML
- High speed (52 rec/s) because the API has no strict rate limiting

---

## 4. Steam

**Spec file:** steam_reviews.yaml
**Strategy:** static (curl_cffi only)
**Data flow:** Detail only (direct reviews API requests)

### How it works

1. Direct request to Steam Reviews API:
   https://store.steampowered.com/appreviews/{app_id}?json=1&filter=recent&language=all&num_per_page=50&cursor=*
2. Pagination via cursor (value comes in the response body)
3. End of data: cursor did not change or reviews array is empty

### How to find the App ID

In the game page URL: https://store.steampowered.com/app/1091500/Cyberpunk_2077/
App ID = 1091500

### Parameters

    app_id            Numeric game ID from the Steam URL
    detail_max_pages  Review pages (each = 50 reviews, 0 = all)

### Limitations

- Fully public API, no authorisation required
- language=all collects reviews in all languages
- filter=recent sorts by date (can be changed to helpful in YAML)
- The language field in each record allows post-collection filtering

---

## 5. Habr

**Spec file:** habr_search.yaml
**Strategy:** static (curl_cffi only)
**Data flow:** List (Search API) → Detail (article API)

### How it works

1. Search API request:
   https://habr.com/kek/v2/articles/?query={keyword}&order=relevance&fl=ru&hl=ru&page=1&perPage=20
2. Numeric article IDs extracted from publicationRefs
3. For each ID: https://habr.com/kek/v2/articles/{id}/?fl=ru&hl=ru
4. Extracted: title, author, date, statistics, full HTML text

### Parameters

    keyword     Search query (e.g. "Python", "machine learning")
    max_pages   Search API pages (each = 20 articles)

### Limitations

- The /kek/v2/ internal API is unofficial and may change
- Speed: ~1.4 rec/s (two requests per article)
- Articles are filtered by language: fl=ru (Russian only)
- The text field contains HTML markup and requires processing for analysis

---

## 6. Lenta.ru

**Spec file:** lenta_search.yaml
**Strategy:** static (curl_cffi only)
**Data flow:** List (Search API v2) → Detail (article HTML)

### How it works

1. Search API v2 request:
   https://lenta.ru/search/v2/process?query={keyword}&from=0&size=10&sort=2&title_only=0&domain=1
2. Article URLs and metadata extracted from the matches array
3. Non-text types are skipped (galleries, videos, live blogs)
4. For each article: HTML loaded → extracted from <script class="json-topic-info">
5. If json-topic-info is absent — CSS selector fallback

### Parameters

    keyword     Search query
    max_pages   Search API pages (each = 10 articles)

### Limitations

- API returns at most 10 000 results (from= <= 9990)
- sort=2 sorts by relevance
- Full text is only available through the article HTML (not via the API)
- Speed: ~1.2 rec/s (two requests per article)

---

## 7. Otzovik

**Spec file:** otzovik_reviews.yaml
**Strategy:** browser (Camoufox only)
**Data flow:** List (HTML review list) → Detail (HTML review page)

### How it works

1. Camoufox browser opened (Firefox with anti-detection patches)
2. Page loaded: https://otzovik.com/reviews/{keyword}/
3. If Yandex SmartCaptcha detected — a 300-second timer is shown in UI
4. User solves the CAPTCHA in the open browser window
5. Review links extracted, each review page visited
6. HTML saved, parsed via BeautifulSoup

### Parameters

    direct_url  Full URL of the reviews page on Otzovik
                Example: https://otzovik.com/reviews/kinopoisk_ru-onlayn-kinoteatr/
    max_pages   Review list pages

### Limitations

- Requires a visible browser (not headless)
- Yandex SmartCaptcha appears almost every time
- Speed heavily depends on page load times
- RAM usage: 800–1400 MB due to the browser

---

## 8. Adding a new source

Finist Crawler supports adding new sources via YAML without editing Python code.

### Steps

1. Create the file specs/my_source.yaml
2. Specify the required fields: source_key, version, flow
3. Configure crawler.list and/or crawler.detail
4. Choose an extraction_mode: html, json, or a custom one

### Available extraction modes

    html          BeautifulSoup + CSS selectors
    json          JMESPath expressions
    reddit        Special recursive Reddit parser
    steam         Special Steam cursor parser
    lenta_search  Special Lenta.ru Search API parser
    lenta_article Special Lenta.ru HTML parser

### Minimal template (HTML source)

    source_key: my_reviews
    version: v1
    description: My new source
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

5. Restart the application. The new source will appear in the list once you add its card to ui/pages/launcher.py in the SOURCES list.