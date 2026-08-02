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
import xml.etree.ElementTree as ET
 
# ---------- Config ----------
HN_TOP_STORIES_URL = "https://hacker-news.firebaseio.com/v0/topstories.json"
HN_ITEM_URL = "https://hacker-news.firebaseio.com/v0/item/{}.json"
HN_STORY_LIMIT = 12
HN_MIN_SCORE = 40
HN_MAX_AGE_HOURS = 30
 
SUBREDDITS = ["LocalLLaMA", "MachineLearning", "artificial"]
REDDIT_POST_LIMIT = 5
REDDIT_HEADERS = {"User-Agent": "daily-digest-script/2.0"}
 
GITHUB_TRENDING_URL = "https://github.com/trending"
GITHUB_TRENDING_LIMIT = 10
 
RSS_FEEDS = {
    "TechCrunch AI": "https://techcrunch.com/category/artificial-intelligence/feed/",
    "VentureBeat AI": "https://venturebeat.com/category/ai/feed/",
}
RSS_ITEM_LIMIT = 8
 
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
 
    items = []
    for item in root.findall(".//item")[:RSS_ITEM_LIMIT]:
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
 
    return raw
 
 
def build_raw_text_blob(raw):
    """Flatten everything into plain text for Gemini to read."""
    lines = []
    for source, (items, error) in raw.items():
        lines.append(f"### {source}")
        if error:
            lines.append(f"(unavailable: {error})")
        elif not items:
            lines.append("(no items)")
        else:
            for it in items:
                lines.append(f"- {it['title']}")
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
    prompt = f"""You are curating a daily tech/AI briefing for a developer who wants
to know what actually matters today — not a dump of links.
 
From the raw headlines and repo names below (pulled from Hacker News, Reddit,
GitHub Trending, and AI news feeds), produce a SHORT, SCANNABLE briefing with
these sections, but ONLY include a section if you have genuinely relevant items:
 
NEW LAUNCHES — new AI models, tools, or products that just shipped
COMPANY NEWS — funding, acquisitions, shutdowns, major pivots
TRENDING ON GITHUB — repos gaining fast traction and why they matter
OTHER NOTABLE STORIES — anything else genuinely significant
 
STRICT rules:
- Maximum 3 items per section. Pick only the most important ones — quality over
  completeness.
- One line per item: a short headline, a dash, then a 1-sentence "why it matters".
- PLAIN TEXT ONLY. Do not use asterisks, markdown bold, hashtags, or any
  formatting symbols — Telegram will display them as literal characters, not
  formatting. Use section titles in plain capital letters as shown above.
- Skip duplicate stories covering the same event.
- Skip low-signal or purely speculative items.
- If nothing qualifies for a section, omit that section entirely.
- Do not invent stories that aren't in the raw data below.
- The ENTIRE briefing must be under 200 words. This is a hard limit — be ruthless
  about cutting less important items to stay under it.
 
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
 
 
def send_telegram_message(text, bot_token, chat_id):
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    chunk_size = 4000
 
    for i in range(0, len(text), chunk_size):
        chunk = text[i:i + chunk_size]
        payload = {
            "chat_id": chat_id,
            "text": chunk,
            "disable_web_page_preview": True,
        }
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
        # Fall back to sending raw data so the run isn't a total loss
        curated = "Curation step failed today — here's the raw feed instead:\n\n" + raw_text
 
    links_block = build_top_links(raw, limit=5)
    final_message = f"BRIEFING - {today}\n{'=' * 30}\n\n{curated}\n{links_block}"
 
    print("\n=== FINAL MESSAGE ===")
    print(final_message)
 
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
 
    if not bot_token or not chat_id:
        print("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set — skipping send.", file=sys.stderr)
        return
 
    send_telegram_message(final_message, bot_token, chat_id)
    print("\nBriefing sent to Telegram.")
 
 
if __name__ == "__main__":
    main()
 
