#!/usr/bin/env python3
"""
Daily News Digest — pulls top stories from Hacker News + AI-focused subreddits,
then sends the digest to you via a Telegram bot ("Harry").
 
Usage (local test):
    TELEGRAM_BOT_TOKEN=xxx TELEGRAM_CHAT_ID=xxx python3 news_digest.py
 
In GitHub Actions, these two env vars are injected from repo secrets —
see the workflow file for details.
 
Requires:
    pip install requests
"""
 
import requests
import datetime
import time
import os
import sys
 
# ---------- Config ----------
HN_TOP_STORIES_URL = "https://hacker-news.firebaseio.com/v0/topstories.json"
HN_ITEM_URL = "https://hacker-news.firebaseio.com/v0/item/{}.json"
HN_STORY_LIMIT = 10          # how many HN stories to show
HN_MIN_SCORE = 50            # skip low-signal stories
HN_MAX_AGE_HOURS = 30        # only stories from roughly the last day
 
SUBREDDITS = ["LocalLLaMA", "MachineLearning", "artificial"]
REDDIT_POST_LIMIT = 5        # per subreddit
REDDIT_HEADERS = {"User-Agent": "daily-digest-script/1.0"}
# -----------------------------
 
 
def fetch_hn_stories():
    """Fetch top Hacker News stories from the last ~day, sorted by score."""
    try:
        ids = requests.get(HN_TOP_STORIES_URL, timeout=10).json()
    except Exception as e:
        return [], f"Could not reach Hacker News API: {e}"
 
    now = time.time()
    stories = []
 
    # Only check the first ~60 ids to keep this fast; HN topstories is already
    # roughly ranked, so we don't need to scan the whole list.
    for story_id in ids[:60]:
        try:
            item = requests.get(HN_ITEM_URL.format(story_id), timeout=10).json()
        except Exception:
            continue
 
        if not item or item.get("type") != "story":
            continue
 
        age_hours = (now - item.get("time", now)) / 3600
        if age_hours > HN_MAX_AGE_HOURS:
            continue
        if item.get("score", 0) < HN_MIN_SCORE:
            continue
 
        stories.append({
            "title": item.get("title", "(no title)"),
            "score": item.get("score", 0),
            "url": item.get("url", f"https://news.ycombinator.com/item?id={story_id}"),
            "comments": item.get("descendants", 0),
        })
 
        if len(stories) >= HN_STORY_LIMIT:
            break
 
    stories.sort(key=lambda s: s["score"], reverse=True)
    return stories, None
 
 
def fetch_reddit_top(subreddit):
    """Fetch today's top posts from a subreddit using Reddit's public JSON endpoint."""
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
            "comments": p.get("num_comments", 0),
        })
    return posts, None
 
 
def build_digest():
    today = datetime.date.today().isoformat()
    lines = [f"DAILY DIGEST — {today}", "=" * 30, ""]
 
    # --- Hacker News ---
    lines.append("HACKER NEWS (top stories, last ~24h)")
    lines.append("-" * 40)
    hn_stories, hn_error = fetch_hn_stories()
    if hn_error:
        lines.append(hn_error)
    elif not hn_stories:
        lines.append("No stories matched the score/age filters today.")
    else:
        for s in hn_stories:
            lines.append(f"• {s['title']} ({s['score']} pts, {s['comments']} comments)")
            lines.append(f"  {s['url']}")
    lines.append("")
 
    # --- Reddit ---
    for sub in SUBREDDITS:
        lines.append(f"r/{sub} (top today)")
        lines.append("-" * 40)
        posts, err = fetch_reddit_top(sub)
        if err:
            lines.append(err)
        elif not posts:
            lines.append("No posts found.")
        else:
            for p in posts:
                lines.append(f"• {p['title']} ({p['score']} pts, {p['comments']} comments)")
                lines.append(f"  {p['url']}")
        lines.append("")
 
    return "\n".join(lines)
 
 
def send_telegram_message(text, bot_token, chat_id):
    """Send a message via the Harry bot. Telegram limits messages to 4096 chars,
    so split into chunks if needed."""
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    chunk_size = 4000
 
    for i in range(0, len(text), chunk_size):
        chunk = text[i:i + chunk_size]
        payload = {
            "chat_id": chat_id,
            "text": chunk,
            # Deliberately no parse_mode: Telegram's Markdown parser throws errors
            # on unescaped *, _, [, ( characters, which real article titles contain
            # often enough that it's not worth the risk. Plain text is more reliable.
            "disable_web_page_preview": True,
        }
        resp = requests.post(url, data=payload, timeout=10)
        if not resp.ok:
            print(f"Telegram send failed: {resp.status_code} {resp.text}", file=sys.stderr)
 
 
def main():
    digest = build_digest()
    print(digest)  # always print to logs, useful for debugging in Actions
 
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
 
    if not bot_token or not chat_id:
        print(
            "\nTELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set — skipping Telegram send. "
            "Digest was printed above only.",
            file=sys.stderr,
        )
        return
 
    send_telegram_message(digest, bot_token, chat_id)
    print("\nDigest sent to Telegram.")
 
 
if __name__ == "__main__":
    main()
 
