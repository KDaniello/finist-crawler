<div align="center">

# 🦅 Finist Crawler

**A desktop application for collecting data from open sources**

*For educators, researchers, analysts and everyone who works with text data*

[![Python](https://img.shields.io/badge/Python-3.13+-blue?style=flat-square&logo=python)](https://python.org)
[![Flet](https://img.shields.io/badge/UI-Flet-cyan?style=flat-square)](https://flet.dev)
[![License](https://img.shields.io/badge/License-MIT-green?style=flat-square)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20macOS-lightgrey?style=flat-square)](https://github.com)

</div>

---

🌐 [Русский](README.md) | English

---

## What is this

Finist Crawler is a tool for automatic collection of text data from popular platforms.
You choose a source, enter a search query, and receive a structured Excel or CSV file.
Everything is done through a clean desktop interface — pick the platform,
set how much to collect and which keywords to use.

**Who it is for:**
- Educators building lesson datasets and student corpora
- Humanities researchers assembling text corpora for analysis
- Marketers studying reviews and community discussions
- Journalists investigating public opinion
- Analysts working with user-generated content

---

## Supported sources

| Source      | Data type                    | Method             | Speed        | Records per session |
|-------------|------------------------------|--------------------|--------------|---------------------|
| Reddit      | Comments and discussions     | API (curl_cffi)    | 57 rec/s     | 2 816+              |
| 2GIS        | Business reviews             | API (curl_cffi)    | 52 rec/s     | 6 016+              |
| Steam       | Game reviews                 | API (curl_cffi)    | 20 rec/s     | 999+                |
| Habr        | Technical articles           | API (curl_cffi)    | 1.4 rec/s    | 188+                |
| Lenta.ru    | News articles                | API (curl_cffi)    | 1.2 rec/s    | 88+                 |
| Otzovik     | Product and service reviews  | Browser (Camoufox) | ~0.3 rec/s   | depends on page     |

Results measured on a Windows 11 test machine, Python 3.11, no proxy.
Speed varies depending on your internet connection and server load.

---

## How to use

### 1. Choose a source

On the Launch page, click a platform card to select it.
The card will highlight in green.

### 2. Enter a parameter

Depending on the source, enter:

- A keyword — for Reddit, Habr, Lenta, 2GIS
- A game App ID — for Steam (the number from the game URL on store.steampowered.com)
- A page URL — for Otzovik (https://otzovik.com/reviews/product-name/)
  Example: https://otzovik.com/reviews/kinopoisk_ru-onlayn-kinoteatr/

### 3. Configure volume

    Search depth    How many result pages to crawl
    Collection size How many items to process (0 = all found)

### 4. Monitor progress

After clicking "Start crawling", the application automatically switches
to the monitoring page, which shows:

- Number of collected records in real time
- Progress per crawling branch
- CPU and RAM load
- Event log

### 5. Export results

On the Results page, select a session and click CSV or XLSX.
The file is saved alongside the data in data/session_*/source_name/.

---

## Performance

Measurements taken on real data (see benchmark_results.json):

    Total collected:          10 107 records
    Average speed:            26.3 rec/s
    Peak RAM usage:           238 MB
    Successful sources:       5/5

Breakdown by source:

    Source       Time     Records   Speed        RAM peak
    ──────────────────────────────────────────────────────
    Reddit       49 s     2 816     57.4 rec/s   229 MB
    2GIS         116 s    6 016     51.7 rec/s   238 MB
    Steam        50 s     999       20.0 rec/s   227 MB
    Habr         136 s    188       1.4 rec/s    229 MB
    Lenta.ru     73 s     88        1.2 rec/s    236 MB

Why are Habr and Lenta slower?

Two-stage crawling: first the article list is fetched from the search API,
then the full text of each article is retrieved in a separate request.
Speed is intentionally limited by the built-in rate limiter
to respect each platform's fair-use expectations.

---

## Data structures

Every record is stored in JSONL format. Fields vary by source.

Reddit:

    {
      "author":      "username",
      "text":        "comment text",
      "likes":       "42",
      "created_at":  "1704067200",
      "depth":       0,
      "title":       "post title",
      "external_id": "abc123",
      "message_url": "https://reddit.com/r/.../",
      "metadata":    {"extracted_at": "2024-01-01T00:00:00+00:00"}
    }

2GIS:

    {
      "external_id": "finist-abc123",
      "text":        "review text",
      "author":      "Username",
      "created_at":  "2024-01-15T10:30:00",
      "rating":      "5",
      "message_url": "https://2gis.ru/...",
      "metadata":    {"extracted_at": "2024-01-01T00:00:00+00:00"}
    }

Steam:

    {
      "review_id":                 "12345678",
      "author_steamid":            "76561198...",
      "playtime_at_review_hours":  12.5,
      "playtime_total_hours":      87.3,
      "is_positive":               "True",
      "text":                      "review text",
      "votes_up":                  "23",
      "language":                  "russian",
      "created_at":                "1704067200",
      "message_url":               "https://store.steampowered.com/...",
      "metadata":                  {"extracted_at": "2024-01-01T00:00:00+00:00"}
    }

---

## Technical details

### Architecture

The application is built on the Zero Infrastructure principle — no databases,
message brokers, or servers required. All components run locally.

    UI (Flet)
        └── AppController
                └── Dispatcher (multiprocessing spawn)
                        └── Worker Process
                                └── FallbackOrchestrator
                                        ├── LightExecutor  (curl_cffi, 15 MB RAM)
                                        └── StealthExecutor (Camoufox, ~200 MB RAM)
                                                └── JSONL files on disk

Imports are strictly one-directional: core → engine → bots → ui.
Violating this order is an architectural error.

### Anti-blocking system

Finist uses a three-level protection bypass system:

1. TLS fingerprint masking
   JA3 fingerprint is spoofed to match real Chrome via curl_cffi.
   Memory cost: 15 MB RAM. Bypasses most static blocks.

2. Human delay
   Random pauses between requests (1–3 s) via TokenBucket
   with adaptive slowdown on HTTP 429.

3. Browser fallback
   When Cloudflare, a CAPTCHA, or a 403 is detected, Camoufox
   (Firefox with anti-detection patches) is launched automatically.
   It simulates human behaviour: Bézier-curve mouse paths,
   randomised scrolling, and automatic Cloudflare Turnstile waiting.

### Resource consumption

    Mode                    RAM           CPU
    ────────────────────────────────────────────
    Idle                    ~110 MB       < 1%
    Crawling (curl_cffi)    ~230 MB       5–15%
    Crawling (Camoufox)     ~800–1400 MB  15–30%

### Data storage

- Records are written line-by-line to JSONL (atomic append, crash-safe)
- Each session gets its own folder: data/session_YYYY-MM-DD_HH-MM-SS/
- CSV and XLSX export without pandas (openpyxl only)
- Logs rotate automatically (5 MB × 3 files)

---

## Ethics

Finist Crawler is intended for research and educational use.
When using the tool:

- Respect each site's robots.txt (the built-in rate limiter is configured
  to stay within acceptable limits — any code changes that risk IP bans
  are the user's responsibility)
- Do not exceed a reasonable request rate (the rate limiter helps)
- Do not collect personal data unless strictly necessary
- Comply with each platform's terms of service

---

## License

MIT License — see the LICENSE file.