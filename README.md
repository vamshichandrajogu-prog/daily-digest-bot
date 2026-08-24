# Daily Digest Bot

An automated daily news briefing delivered straight to Telegram — no server,
no local machine, no manual work. Runs entirely on GitHub Actions' free tier
and sends a categorized digest via a Telegram bot each morning.

## What it does

Every day, this pulls raw signals from several free sources, sends them to
Gemini for curation into a short, categorized briefing, and delivers it to
your phone via Telegram — automatically, on a schedule.

**Sources pulled:**
- Hacker News (top stories from the last ~24h)
- Reddit: r/LocalLLaMA, r/MachineLearning, r/artificial, r/worldnews, r/technology, r/india
- GitHub Trending (scraped)
- Google News RSS search (with a built-in `when:1d` filter for AI/tech, world, and India-specific news)

**Output format:** a fixed mix, grouped into sections:
- 3–4 AI & Tech items
- 2–3 World news items (spread across regions, not just one country)
- 1–2 India-specific items
- 1–2 Trending GitHub repos

Each item is a bold topic name, one short sentence of context, and a source
link (auto-shortened via TinyURL if it's long enough to wrap across multiple
lines on a phone screen).

## Files in this repo

| File | Purpose |
|---|---|
| `news_digest_v2.py` | The main script — fetches, curates, and sends the digest |
| `.github/workflows/daily-digest.yml` | GitHub Actions workflow that runs the script on a schedule |

## Setup

### 1. Create a Telegram bot
1. Open Telegram, message **@BotFather**
2. Send `/newbot`, follow the prompts to name it and give it a username
3. Save the **bot token** BotFather gives you

### 2. Get your Telegram chat ID
1. Send any message to your new bot
2. Open `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates` in a browser
3. Find `"chat":{"id":XXXXXXXXX,...}` in the response — that number is your chat ID

### 3. Get a Gemini API key
Go to [aistudio.google.com](https://aistudio.google.com) (or [console.cloud.google.com](https://console.cloud.google.com) if you already use Google Cloud) and generate an API key. Gemini has a free tier suitable for this use case.

### 4. Add repo secrets
In this repo: **Settings → Secrets and variables → Actions → New repository secret**. Add all three:
- `GEMINI_API_KEY`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

### 5. Test it
Go to the **Actions** tab → select the workflow → **Run workflow** to trigger it manually. Check Telegram for the result.

## Customization

- **Change the schedule**: edit the `cron` line in `daily-digest.yml`. GitHub Actions cron runs in UTC, and scheduled runs can be delayed (occasionally by hours during high load), so schedule earlier than your actual target time as a buffer.
- **Change the category mix**: edit the quotas in the prompt inside `curate_with_gemini()`, and update `CATEGORY_CONFIG` in `format_as_telegram_html()` to match (both need to agree, or items may get dropped by the hard-cap safety net).
- **Change sources**: edit `SUBREDDITS`, `GOOGLE_NEWS_QUERIES`, or `RSS_FEEDS` near the top of the script.
- **Change item length/tone**: edit the prompt text in `curate_with_gemini()`.

## Known limitations

- **GitHub Trending is scraped, not an official API.** It's pattern-matching GitHub's current page HTML, so it's the piece most likely to silently break if GitHub changes their page structure. It's built to fail gracefully rather than crash the whole run.
- **Google News RSS search is an unofficial endpoint.** It's widely used and currently reliable, but not a documented, guaranteed-stable Google API.
- **This is a personal-use tool, not hardened for production.** It's built from free/best-effort sources stitched together — good for a daily briefing, not something to build a product on without more error handling and monitoring.
- **LLM curation isn't perfectly deterministic.** Gemini is instructed to follow strict formatting and category quotas, but occasional drift (e.g. one category short by an item) is possible and expected — the script has fallbacks so a formatting slip won't break delivery, it just won't look as polished that day.

## Cost

- **GitHub Actions**: free tier covers this easily — the job runs for well under a minute a day.
- **Gemini API**: free tier is generally sufficient for a single small summarization call per day.
- **Telegram Bot API**: free.
- **TinyURL**: free, no key required.
