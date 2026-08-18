#!/usr/bin/env python3
"""
Daily Tech/AI Briefing — pulls raw signals from several sources, asks Gemini
to curate them into a concise "what actually matters today" brief, then sends
it to you via a Telegram bot ("Harry").
 
Sources pulled:
  - Hacker News (top stories, last ~24h)
  - Reddit: r/LocalLLaMA, r/MachineLearning, r/artificial (top today)
  - GitHub Trending (today, all languages)
  - AI news RSS feeds (TechCrunch AI, VentureBeat AI)
 
Env vars required:
  GEMINI_API_KEY
  TELEGRAM_BOT_TOKEN
  TELEGRAM_CHAT_ID
 
Requires:
  pip install requests
"""
 
import requests
import datetime
import time
import os
import sys
import re
import html
import urllib.parse
from email.utils import parsedate_to_datetime
import xml.etree.ElementTree as ET
 
# ---------- Config ----------
HN_TOP_STORIES_URL = "https://hacker-news.firebaseio.com/v0/topstories.json"
HN_ITEM_URL = "https://hacker-news.firebaseio.com/v0/item/{}.json"
HN_STORY_LIMIT = 12
HN_MIN_SCORE = 40
HN_MAX_AGE_HOURS = 30
 
SUBREDDITS = ["LocalLLaMA", "MachineLearning", "artificial", "worldnews", "technology", "business"]
REDDIT_POST_LIMIT = 5
REDDIT_HEADERS = {"User-Agent": "daily-digest-script/2.0"}
 
GITHUB_TRENDING_URL = "https://github.com/trending"
GITHUB_TRENDING_LIMIT = 10
 
RSS_FEEDS = {
    "TechCrunch AI": "https://techcrunch.com/category/artificial-intelligence/feed/",
    "VentureBeat AI": "https://venturebeat.com/category/ai/feed/",
}
RSS_ITEM_LIMIT = 8
RSS_MAX_AGE_HOURS = 48  # discard articles older than this even if a feed serves them
 
# Google News RSS search supports a "when:1d" operator that filters results to
# the last 24 hours server-side - this is the main fix for stale/old articles
# slipping through, since Google enforces the date filter itself rather than
# us trusting whatever a feed happens to be serving.
GOOGLE_NEWS_QUERIES = {
    "Google News - AI/Tech": "artificial intelligence OR tech launch when:1d",
    "Google News - World/Business": "world news OR business when:1d",
}
GOOGLE_NEWS_ITEM_LIMIT = 8
 
GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
# -----------------------------
 
 
def fetch_hn_stories():
    try:
        ids = requests.get(HN_TOP_STORIES_URL, timeout=10).json()
    except Exception as e:
        return [], f"Could not reach Hacker News API: {e}"
 
    now = time.time()
    stories = []
 
    for story_id in ids[:60]:
        try:
            item = requests.get(HN_ITEM_URL.format(story_id), timeout=10).json()
        except Exception:
            continue
 
        if not item or item.get("type") != "story":
            continue
 
        age_hours = (now - item.get("time", now)) / 3600
        if age_hours > HN_MAX_AGE_HOURS or item.get("score", 0) < HN_MIN_SCORE:
            continue
 
        stories.append({
            "title": item.get("title", "(no title)"),
            "score": item.get("score", 0),
            "url": item.get("url", f"https://news.ycombinator.com/item?id={story_id}"),
        })
 
        if len(stories) >= HN_STORY_LIMIT:
            break
 
    stories.sort(key=lambda s: s["score"], reverse=True)
    return stories, None
 
 
def fetch_reddit_top(subreddit):
    url = f"https://www.reddit.com/r/{subreddit}/top.json?t=day&limit={REDDIT_POST_LIMIT}"
    try:
        resp = requests.get(url, headers=REDDIT_HEADERS, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        return [], f"Could not reach r/{subreddit}: {e}"
 
    posts = []
    for child in data.get("data", {}).get("children", []):
        p = child.get("data", {})
        posts.append({
            "title": p.get("title", "(no title)"),
            "score": p.get("score", 0),
            "url": "https://reddit.com" + p.get("permalink", ""),
        })
    return posts, None
 
 
def fetch_github_trending():
    """Scrape github.com/trending. This is HTML scraping, not an official API,
    so it's the most likely piece to break if GitHub changes their page markup."""
    try:
        resp = requests.get(
            GITHUB_TRENDING_URL,
            headers={"User-Agent": "Mozilla/5.0 (daily-digest-script)"},
            timeout=10,
        )
        resp.raise_for_status()
        html = resp.text
    except Exception as e:
        return [], f"Could not reach GitHub Trending: {e}"
 
    # Repo links on the trending page look like href="/owner/repo" inside <h2> blocks.
    repo_pattern = re.compile(r'href="/([\w.-]+/[\w.-]+)"\s+data-view-component')
    matches = repo_pattern.findall(html)
 
    seen = set()
    repos = []
    for m in matches:
        if m in seen:
            continue
        seen.add(m)
        repos.append({"title": m, "url": f"https://github.com/{m}"})
        if len(repos) >= GITHUB_TRENDING_LIMIT:
            break
 
    if not repos:
        return [], "GitHub Trending page structure may have changed — no repos parsed."
 
    return repos, None
 
 
def fetch_rss(name, url):
    try:
        resp = requests.get(url, headers={"User-Agent": "daily-digest-script/2.0"}, timeout=10)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
    except Exception as e:
        return [], f"Could not reach {name} feed: {e}"
 
    now = datetime.datetime.now(datetime.timezone.utc)
    items = []
    skipped_old = 0
 
    for item in root.findall(".//item")[:RSS_ITEM_LIMIT * 2]:  # scan a few extra since some get filtered by age
        title_el = item.find("title")
        link_el = item.find("link")
        pubdate_el = item.find("pubDate")
 
        if title_el is None or not title_el.text:
            continue
 
        # Actually check the article's age instead of trusting feed order.
        # This is the fix for old/stale articles slipping through as "today's news".
        if pubdate_el is not None and pubdate_el.text:
            try:
                pub_dt = parsedate_to_datetime(pubdate_el.text)
                if pub_dt.tzinfo is None:
                    pub_dt = pub_dt.replace(tzinfo=datetime.timezone.utc)
                age_hours = (now - pub_dt).total_seconds() / 3600
                if age_hours > RSS_MAX_AGE_HOURS:
                    skipped_old += 1
                    continue
            except Exception:
                pass  # if we can't parse the date, don't block the item on that alone
 
        items.append({
            "title": title_el.text.strip(),
            "url": link_el.text.strip() if link_el is not None and link_el.text else "",
        })
 
        if len(items) >= RSS_ITEM_LIMIT:
            break
 
    error = None
    if not items and skipped_old > 0:
        error = f"All {skipped_old} items from {name} were older than {RSS_MAX_AGE_HOURS}h - feed may be stale."
 
    return items, error
 
 
def fetch_google_news(label, query):
    """Google News RSS search with a built-in when:1d filter - Google enforces
    the recency window server-side, which is more reliable than us guessing
    from feed order. Unofficial endpoint (no public API docs from Google), so
    treat as best-effort rather than a guaranteed-stable API."""
    base_url = "https://news.google.com/rss/search"
    params = {"q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"}
    full_url = f"{base_url}?{urllib.parse.urlencode(params)}"
 
    try:
        resp = requests.get(full_url, headers={"User-Agent": "daily-digest-script/2.0"}, timeout=10)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
    except Exception as e:
        return [], f"Could not reach Google News ({label}): {e}"
 
    items = []
    for item in root.findall(".//item")[:GOOGLE_NEWS_ITEM_LIMIT]:
        title_el = item.find("title")
        link_el = item.find("link")
        if title_el is not None and title_el.text:
            items.append({
                "title": title_el.text.strip(),
                "url": link_el.text.strip() if link_el is not None and link_el.text else "",
            })
    return items, None
 
 
def collect_raw_signals():
    """Gather everything into one structure: {source_label: (items, error)}"""
    raw = {}
 
    raw["Hacker News"] = fetch_hn_stories()
    for sub in SUBREDDITS:
        raw[f"r/{sub}"] = fetch_reddit_top(sub)
    raw["GitHub Trending"] = fetch_github_trending()
    for name, url in RSS_FEEDS.items():
        raw[name] = fetch_rss(name, url)
    for label, query in GOOGLE_NEWS_QUERIES.items():
        raw[label] = fetch_google_news(label, query)
 
    return raw
 
 
def build_raw_text_blob(raw):
    """Flatten everything into plain text for Gemini to read. Each line includes
    the URL inline so Gemini can copy the exact source link rather than guessing."""
    lines = []
    for source, (items, error) in raw.items():
        lines.append(f"### {source}")
        if error:
            lines.append(f"(unavailable: {error})")
        elif not items:
            lines.append("(no items)")
        else:
            for it in items:
                url = it.get("url", "")
                lines.append(f"- {it['title']} | {url}")
        lines.append("")
    return "\n".join(lines)
 
 
def build_top_links(raw, limit=5):
    """Instead of dumping every link from every source, surface just the
    highest-scored items (HN/Reddit have scores; GitHub/RSS don't, so they're
    included at a flat baseline). Keeps the message short."""
    all_items = []
    for source, (items, error) in raw.items():
        if error or not items:
            continue
        for it in items:
            if not it.get("url"):
                continue
            all_items.append({
                "title": it["title"],
                "url": it["url"],
                "score": it.get("score", 0),
                "source": source,
            })
 
    all_items.sort(key=lambda x: x["score"], reverse=True)
    top = all_items[:limit]
 
    if not top:
        return ""
 
    lines = ["\nTOP LINKS"]
    for it in top:
        short_title = it["title"][:60] + ("..." if len(it["title"]) > 60 else "")
        lines.append(f"- {short_title} ({it['source']})\n  {it['url']}")
    return "\n".join(lines)
 
 
def curate_with_gemini(raw_text, api_key):
    """Send the raw headline dump to Gemini and ask it to produce a categorized,
    breaking-news-style brief."""
    prompt = f"""You are curating a daily "what's actually trending" briefing —
a mix of AI/tech news AND general world/business news, not just AI.
 
Below is raw data pulled from Hacker News, several subreddits (both tech/AI
ones and general ones like r/worldnews, r/technology, r/business), GitHub
Trending, and AI news feeds. Each line has a title and its exact URL separated
by " | ".
 
Pick the 7 to 9 MOST significant, genuinely trending topics from across ALL
of this raw data — mix AI/tech stories with general world/business/science
stories. Do not over-index on AI just because some sources are AI-focused;
give a balanced picture of what's actually significant today across domains.
 
Output EACH topic using EXACTLY this structure (including the tags TOPIC/INFO/SOURCE
literally as shown), one block per topic, with a blank line between blocks:
 
TOPIC: <short topic name, 5-8 words max>
INFO: <ONE tight sentence, max 20 words, explaining what happened and why it matters>
SOURCE: <exact URL from the raw data for this item>
 
STRICT rules:
- Prioritize items that read as genuinely NEW today - a fresh announcement,
  launch, or event. If a headline describes something that sounds like it may
  have happened a while ago (e.g. phrased as an established fact rather than
  a new development), deprioritize it in favor of clearly fresh items.
- INFO must be exactly ONE sentence, maximum 20 words. Do not write 2-3 sentences.
  Be ruthless about cutting to the single most important fact.
- Use the EXACT URL from the raw data for each topic's SOURCE line. Never
  invent, guess, or modify a URL. If you can't find a clean URL for a topic,
  skip that topic and pick a different one instead.
- PLAIN TEXT ONLY inside TOPIC and INFO — no asterisks, markdown, hashtags, or
  bullet symbols.
- Skip duplicate stories covering the same event.
- Skip low-signal, speculative, or purely promotional items.
- Do not invent stories that aren't in the raw data below.
- Output ONLY the TOPIC/INFO/SOURCE blocks — no extra headers, intro, or closing text.
 
RAW DATA:
{raw_text}
"""
 
    payload = {
        "contents": [
            {"role": "user", "parts": [{"text": prompt}]}
        ]
    }
    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": api_key,
    }
 
    try:
        resp = requests.post(GEMINI_URL, headers=headers, json=payload, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        candidates = data.get("candidates", [])
        if not candidates:
            return None, f"Gemini returned no candidates: {data}"
        parts = candidates[0].get("content", {}).get("parts", [])
        text = "".join(p.get("text", "") for p in parts)
        return text.strip(), None
    except Exception as e:
        return None, f"Gemini API call failed: {e}"
 
 
def shorten_url(url):
    """Shorten a URL using TinyURL's free create API - no API key required.
    If shortening fails for any reason, fall back to the original URL so a
    slow/unavailable shortener never breaks message delivery."""
    if not url:
        return url
    try:
        resp = requests.get(
            "https://tinyurl.com/api-create.php",
            params={"url": url},
            timeout=8,
        )
        if resp.ok and resp.text.startswith("http"):
            return resp.text.strip()
    except Exception:
        pass
    return url  # fallback: original (long) URL rather than failing the run
 
 
def format_as_telegram_html(curated_text, date_str):
    """Parse Gemini's TOPIC/INFO/SOURCE blocks and turn them into Telegram HTML,
    with topic names actually bold (using Telegram's <b> tag, which is far more
    forgiving than Markdown mode — it only needs &, <, > escaped)."""
    blocks = re.split(r"\n\s*\n", curated_text.strip())
    parts = [f"<b>{html.escape(date_str)}</b>", ""]
 
    parsed_any = False
    for block in blocks:
        topic_match = re.search(r"TOPIC:\s*(.+)", block)
        info_match = re.search(r"INFO:\s*(.+)", block)
        source_match = re.search(r"SOURCE:\s*(\S+)", block)
 
        if not (topic_match and info_match):
            continue  # skip malformed blocks rather than crash the whole send
 
        parsed_any = True
        topic = html.escape(topic_match.group(1).strip())
        info = html.escape(info_match.group(1).strip())
        parts.append(f"<b>{topic}</b>")
        parts.append(info)
        if source_match:
            short_url = shorten_url(source_match.group(1).strip())
            # Plain URL text - Telegram auto-links bare URLs regardless of parse_mode,
            # no need for an <a> tag.
            parts.append(f"Source: {short_url}")
        parts.append("")
 
    if not parsed_any:
        # Gemini didn't follow the structured format - fall back to raw text so
        # the run isn't wasted, just less pretty.
        parts.append(html.escape(curated_text))
 
    return "\n".join(parts)
 
 
def send_telegram_message(text, bot_token, chat_id, use_html=False):
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    chunk_size = 4000
 
    for i in range(0, len(text), chunk_size):
        chunk = text[i:i + chunk_size]
        payload = {
            "chat_id": chat_id,
            "text": chunk,
            "disable_web_page_preview": True,
        }
        if use_html:
            payload["parse_mode"] = "HTML"
        resp = requests.post(url, data=payload, timeout=10)
        if not resp.ok:
            print(f"Telegram send failed: {resp.status_code} {resp.text}", file=sys.stderr)
 
 
def main():
    today = datetime.date.today().isoformat()
    raw = collect_raw_signals()
    raw_text = build_raw_text_blob(raw)
 
    print("=== RAW SIGNALS (debug) ===")
    print(raw_text)
 
    gemini_key = os.environ.get("GEMINI_API_KEY")
    if not gemini_key:
        print("GEMINI_API_KEY not set — cannot curate. Exiting.", file=sys.stderr)
        sys.exit(1)
 
    curated, error = curate_with_gemini(raw_text, gemini_key)
    if error:
        print(f"Curation failed: {error}", file=sys.stderr)
        # Fall back to sending raw data so the run isn't a total loss. Plain
        # text here (not HTML) since raw scraped titles may contain characters
        # that aren't valid/escaped HTML.
        fallback_text = "Curation step failed today — here's the raw feed instead:\n\n" + raw_text
        links_block = build_top_links(raw, limit=5)
        final_message = f"{today}\n{'=' * 30}\n\n{fallback_text}\n{links_block}"
        use_html = False
    else:
        final_message = format_as_telegram_html(curated, today)
        use_html = True
 
    print("\n=== FINAL MESSAGE ===")
    print(final_message)
 
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
 
    if not bot_token or not chat_id:
        print("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set — skipping send.", file=sys.stderr)
        return
 
    send_telegram_message(final_message, bot_token, chat_id, use_html=use_html)
    print("\nBriefing sent to Telegram.")
 
 
if __name__ == "__main__":
    main()
 
