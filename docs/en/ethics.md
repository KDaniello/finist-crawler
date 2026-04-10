# Ethics of Using Finist Crawler

🌐 [Читать на русском](../ru/ethics.md)

---

## Contents

1. Intended purpose
2. Built-in technical safeguards
3. Rules for users
4. Legal context
5. When in doubt

---

## 1. Intended purpose

Finist Crawler is built for **research and educational purposes**:

- Building text corpora for linguistic analysis
- Creating training datasets for classes and courses
- Studying public discourse in social media
- Monitoring review sentiment for academic work
- Journalistic investigation of public opinion

The tool is **not intended** for:

- Commercial resale of collected data
- Creating spam or mass mailings
- Bypassing paid subscriptions or closed content
- Collecting personal data for surveillance

---

## 2. Built-in technical safeguards

Finist Crawler includes several technical mechanisms that already
respect basic ethical norms by default.

### Rate Limiter (TokenBucket)

Each source has a configured request-per-second limit.
The values are chosen to avoid generating traffic
that is distinguishable from an active human user:

    Reddit      1.0 req/s    (+ warmup pauses 0.7–2.1 s)
    2GIS        1.5 req/s
    Steam       0.9 req/s
    Habr        10.0 req/s   (API allows it)
    Lenta.ru    3.0 req/s
    Otzovik     1.5 req/s    (browser-based, inherently slower)

### Adaptive slowdown

On receiving HTTP 429 (Too Many Requests), the rate limiter
automatically halves the speed and continues reducing it
on repeated 429 responses. Maximum slowdown: 10× the base rate.

### Human delay

A random pause (1–3 seconds) with ±20% jitter is added between requests.
This mimics real user behaviour and reduces the risk of automatic blocking.

### Warning

Changing rate limiter parameters in YAML or Python code
(increasing requests_per_second, reducing delays) may result in
an IP ban. The user bears full responsibility for such changes.

---

## 3. Rules for users

### Respect robots.txt

Before collecting data, read the site's robots.txt file.
It specifies which sections are off-limits for automated crawling.

Example: https://www.reddit.com/robots.txt

Finist Crawler does not check robots.txt automatically —
this check is the user's responsibility.

### Do not collect personal data unnecessarily

User data (names, avatars, IDs) is collected only to the extent
it is present in public APIs and necessary to identify a record.
Do not use collected data to de-anonymise or profile specific individuals.

### Comply with platform Terms of Service

Each platform has a terms of service that governs automated data collection:

    Reddit   https://www.redditinc.com/policies/data-api-terms
    Steam    https://store.steampowered.com/privacy_agreement/
    2GIS     https://law.2gis.ru/api-rules

Make sure your use case does not violate these rules.

### Do not overload servers

Use the minimum number of pages necessary.
If you need 100 reviews — do not set a limit of 10 000.

---

## 4. Legal context

### In Russia

Collecting publicly available information from the internet
for research and educational purposes generally does not conflict
with Russian law, provided the following conditions are met:

- Data is obtained from publicly accessible sources
- Data does not constitute personal data under Federal Law 152-FZ
  (or is anonymised before analysis)
- Collected data is not transferred to third parties
  for commercial purposes

Federal Law 273-FZ (on computer information) does not apply
to obtaining publicly available data via standard HTTP requests.

### In the EU / USA

In academic and journalistic contexts, collecting public data
is protected by the Fair Use principle (USA) and the research exemption
in GDPR (EU), provided data minimisation is applied
and there is no commercial use.

This is not legal advice.
If in doubt, consult an information law specialist.

---

## 5. When in doubt

If you are unsure whether collecting data from a specific site is permissible:

1. Read the site's robots.txt and Terms of Service
2. Check whether the site provides an official API
   (Reddit and Steam, for example, offer official APIs)
3. Contact the site's support team describing your research
4. Use the minimum amount of data necessary
5. Anonymise the data before publishing your research results