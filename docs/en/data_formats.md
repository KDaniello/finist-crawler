# Finist Crawler — Data Formats

🌐 [Читать на русском](../ru/data_formats.md)

---

## Contents

1. Common fields
2. Reddit
3. 2GIS
4. Steam
5. Habr
6. Lenta.ru
7. Otzovik
8. Export formats
9. On-disk storage

---

## 1. Common fields

Every record, regardless of source, contains three mandatory fields.

    external_id   Unique record identifier.
                  Either taken from the source API or computed
                  deterministically via MD5 of (url + author + text).
                  Format for computed IDs: "finist-<16 hex characters>"

    message_url   Direct link to the page from which the record was taken.

    metadata      A service object.
                  metadata.extracted_at — ISO 8601 timestamp of collection.

---

## 2. Reddit

Source: reddit_comments.yaml
Strategy: two-stage (post search → recursive comment extraction)

    {
      "author":      "Reddit username",
      "text":        "comment text (newlines replaced with spaces)",
      "likes":       "total score",
      "created_at":  "Unix timestamp of creation",
      "depth":       "nesting depth (0 = top level)",
      "title":       "parent post title",
      "reply_to_id": "parent comment ID (t1_xxxxx)",
      "external_id": "comment ID from Reddit API",
      "message_url": "https://www.reddit.com/r/.../comments/.../.json",
      "metadata":    {"extracted_at": "2024-01-01T00:00:00+00:00"}
    }

Notes:
- Comments are extracted recursively, including nested replies
- Deleted comments ([deleted], [removed]) are skipped
- The depth field allows reconstruction of the discussion tree
- Speed is limited to 1 rec/s due to Reddit API policy

---

## 3. 2GIS

Source: twogis_search.yaml
Strategy: two-stage (HTML search → JSON reviews API)

    {
      "external_id": "finist-<16 hex>  or  ID from 2GIS API",
      "text":        "review text",
      "author":      "username",
      "created_at":  "ISO 8601 creation date (2024-01-15T10:30:00)",
      "rating":      "rating from 1 to 5",
      "message_url": "https://public-api.reviews.2gis.com/...",
      "metadata":    {"extracted_at": "2024-01-01T00:00:00+00:00"}
    }

Notes:
- First stage: HTML search page parsing, business IDs extracted
  via regex from links like /moscow/firm/4504127908559765
- Second stage: requests to the open JSON reviews API without auth
- Pagination via offset (50 reviews per request)
- Fastest source: up to 52 records/sec

---

## 4. Steam

Source: steam_reviews.yaml
Strategy: single-stage (direct reviews API by App ID)

    {
      "review_id":                "Steam review ID",
      "author_steamid":           "64-bit Steam ID of the author",
      "playtime_at_review_hours": 12.5,
      "playtime_total_hours":     87.3,
      "is_positive":              "True or False",
      "text":                     "review text",
      "votes_up":                 "number of helpful votes",
      "votes_funny":              "number of funny votes",
      "created_at":               "Unix timestamp of creation",
      "language":                 "review language (russian, english...)",
      "steam_purchase":           "True — purchased on Steam",
      "game_appid":               "numeric App ID of the game",
      "message_url":              "https://store.steampowered.com/appreviews/...",
      "metadata":                 {"extracted_at": "2024-01-01T00:00:00+00:00"}
    }

Notes:
- playtime_at_review_hours and playtime_total_hours are converted from minutes to hours
- Pagination via cursor (Steam API): cursor value changes with every page
- End of data: cursor did not change or reviews array is empty
- The language field allows filtering reviews by language

---

## 5. Habr

Source: habr_search.yaml
Strategy: two-stage (Search API → article API)

    {
      "external_id": "numeric article ID on Habr",
      "title":       "article title (may contain HTML tags)",
      "author":      "author alias",
      "created_at":  "ISO 8601 publication date",
      "views":       "view count",
      "likes":       "score (rating)",
      "comments":    "comment count",
      "text":        "full article text (HTML)",
      "message_url": "https://habr.com/kek/v2/articles/.../",
      "metadata":    {"extracted_at": "2024-01-01T00:00:00+00:00"}
    }

Notes:
- Habr's internal API (/kek/v2/) returns JSON
- The text field contains the article HTML markup
- List pagination via offset (20 articles per page)
- Slower than other API sources due to two sequential requests per article

---

## 6. Lenta.ru

Source: lenta_search.yaml
Strategy: two-stage (Search API v2 → article HTML)

    {
      "external_id":  "numeric docid from Search API",
      "title":        "article title",
      "excerpt":      "short description from search results",
      "text":         "full article text",
      "author":       "author name (from json-topic-info or CSS)",
      "description":  "additional description (from json-topic-info)",
      "alt_headline": "alternative headline",
      "created_at":   "ISO 8601 publication date",
      "type":         "News / Article / Opinion / ...",
      "rubric":       "Russia / World / Economy / ...",
      "image_url":    "main image URL",
      "source":       "lenta.ru",
      "message_url":  "https://lenta.ru/articles/...",
      "metadata":     {"extracted_at": "2024-01-01T00:00:00+00:00"}
    }

Notes:
- Type filtering: galleries (3), videos (6), live blogs (8) are skipped;
  only text content is collected (types 1, 2, 4, 5)
- Full text is extracted preferentially from <script class="json-topic-info">
  (JSON embedded by Lenta in every page); CSS selectors are used as fallback
- Search API pagination via from= offset parameter
- The API returns at most 10 000 results

---

## 7. Otzovik

Source: otzovik_reviews.yaml
Strategy: two-stage (HTML list → HTML review page)
Method: browser-based (Camoufox)

    {
      "title":       "review title",
      "text":        "full review text",
      "author":      "username",
      "rating":      "rating (1-10)",
      "created_at":  "publication date (YYYY-MM-DD)",
      "likes":       "like count",
      "comments":    "comment count",
      "message_url": "https://otzovik.com/review_XXXXX.html",
      "metadata":    {"extracted_at": "2024-01-01T00:00:00+00:00"}
    }

Notes:
- Requires a browser (Camoufox): Yandex SmartCaptcha activates on curl requests
- When a CAPTCHA appears, a 300-second timer is shown in the monitoring UI
- The user must solve the CAPTCHA in the open browser window manually
- Speed ~0.3 records/sec due to page rendering
- The direct_url field is passed directly (not through a keyword)

---

## 8. Export formats

### CSV

- Encoding: UTF-8 with BOM (utf-8-sig) for correct opening in Excel
- Delimiter: semicolon (;) — compatible with Russian Windows locale
- Newlines inside cell values are replaced with spaces
- Objects (dict, list) are serialised as a JSON string

### XLSX

- Engine: openpyxl (no pandas)
- Headers: bold white font, blue background (#4472C4)
- Text fields (text, body, description): word wrap enabled
- Column widths: auto-fit, maximum 80 characters
- First row frozen (freeze_panes="A2")
- Auto-filter enabled on all columns

---

## 9. On-disk storage

    data/
    └── session_YYYY-MM-DD_HH-MM-SS-ffffff/
        └── <source_key>/
            ├── <source_key>.jsonl
            └── <source_key>_export.csv  (or .xlsx, after export)

JSONL (JSON Lines) — each line is a standalone JSON object.

Advantages over SQLite/CSV as the primary storage format:
- No need to load the entire file into memory
- Appends are atomic: a crash on line N does not corrupt lines 1..N-1
- Human-readable in any text editor
- Direct compatibility with pandas, polars, DuckDB for further analysis