# Daily Digest Bot — Harry

An automated daily briefing delivered straight to Telegram — no local server,
no laptop load, runs entirely on GitHub's free infrastructure.

Every morning, this pulls trending signals from Hacker News, Reddit, GitHub
Trending, and Google News, curates them into a short, categorized briefing
using Gemini, and sends it to a Telegram bot ("Harry").

---

## What you get

A message like this, delivered daily:

```
2026-08-17

AI & TECH
Stripe acquires AI startup OpenRouter
Stripe reportedly agrees to acquire AI gateway startup OpenRouter for over $7 billion.
Source: https://tinyurl.com/...

AROUND THE WORLD
EU plans new Russia sanctions package
The EU foreign chief announced plans for the most far-reaching sanctions package against Russia this autumn.
Source: https://tinyurl.com/...

INDIA
[India-specific hot topic]
...

TRENDING ON GITHUB
[Trending repo]
...
```

**Content mix per day:**
- 3-4 AI/tech stories
- 2-3 world news stories (spread across regions, not just one country)
- 1-2 India-specific stories
- 1-2 trending GitHub repos

---

## How it works

```
GitHub Actions (daily cron)
        │
        ▼
news_digest_v2.py
        │
        ├── Hacker News API (top stories, last ~24h)
        ├── Reddit JSON API (top of day: LocalLLaMA, MachineLearning,
        │     artificial, worldnews, technology, india)
        ├── GitHub Trending (scraped)
        └── Google News RSS (when:1d filter — AI/Tech, World, India)
                │
                ▼
        Gemini API — curates raw headlines into a categorized,
        one-sentence-per-item briefing (strict CATEGORY/TOPIC/
        INFO/SOURCE format, parsed back into Python)
                │
                ▼
        TinyURL — shortens any link over 60 characters
                │
                ▼
        Telegram Bot API — sends the final briefing (HTML formatting,
        real bold section headers and topic names)
```

Everything runs on GitHub's servers on a schedule. Nothing runs on your own
machine.

---

## Files in this repo

| File | Purpose |
|---|---|
| `news_digest_v2.py` | The main script — fetches, curates, formats, and sends the digest |
| `.github/workflows/daily-digest.yml` | GitHub Actions workflow that runs the script on a daily schedule |
| `README.md` | This file |

---

## Setup

### 1. Create a Telegram bot
1. Message **@BotFather** on Telegram
2. Send `/newbot`, follow the prompts, and save the **bot token** it gives you
3. Send any message to your new bot, then visit
   `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates` in a browser to find
   your **chat ID** (look for `"chat":{"id":XXXXXXXXX`)

### 2. Get a Gemini API key
Get a free key at [aistudio.google.com](https://aistudio.google.com) or
[console.cloud.google.com](https://console.cloud.google.com) (Gemini API).

### 3. Add repository secrets
In this repo: **Settings → Secrets and variables → Actions → New repository secret**

Add all three:
| Secret name | Value |
|---|---|
| `GEMINI_API_KEY` | Your Gemini API key |
| `TELEGRAM_BOT_TOKEN` | Your bot token from BotFather |
| `TELEGRAM_CHAT_ID` | Your chat ID from the getUpdates step |

### 4. Test it
Go to **Actions → Daily News Digest → Run workflow** to trigger it manually.
Check Telegram — you should get a message within about a minute.

Once confirmed working, it runs automatically on the schedule set in
`daily-digest.yml` (no further action needed).

---

## Customizing

**Change the schedule:** edit the `cron:` line in
`.github/workflows/daily-digest.yml`. GitHub Actions cron times are in UTC —
convert your target local time accordingly. Scheduled workflows can run
5-30+ minutes late during high load, so schedule a buffer before your actual
target time.

**Change the topic mix:** edit `CATEGORY_CONFIG` and the quota instructions
inside the `curate_with_gemini()` prompt in `news_digest_v2.py`.

**Change sources:** edit `SUBREDDITS`, `GOOGLE_NEWS_QUERIES`, or `RSS_FEEDS`
near the top of `news_digest_v2.py`.

**Change link-shortening threshold:** adjust `URL_SHORTEN_THRESHOLD` (default
60 characters — links shorter than this are left as-is).

---

## Known limitations

- **GitHub Trending scraping is fragile.** It's HTML pattern-matching, not an
  official API — if GitHub changes their page structure, this source may
  silently return nothing (it's built to fail gracefully, not crash the run).
- **Google News RSS is an unofficial endpoint.** It's widely used and stable
  in practice, but not a documented/guaranteed-stable Google API.
- **GitHub Actions scheduled runs aren't exact-time.** Expect some daily
  variance in delivery time.
- **This is a personal-use pipeline**, built from free/unofficial sources
  stitched together — not hardened for production or public redistribution.

---

## Troubleshooting

Check **Actions → (latest run) → send-digest** for logs. Common issues:

- **Exit code 1 / KeyError**: usually a schema mismatch between sources (all
  item dicts should use the same key names, e.g. `title`, not `name`).
- **No Telegram message received but run succeeded**: double-check
  `TELEGRAM_CHAT_ID` and `TELEGRAM_BOT_TOKEN` secrets are correct and that
  you've sent at least one message to the bot first.
- **Curation failed / Gemini error**: check `GEMINI_API_KEY` is valid and has
  remaining quota.
