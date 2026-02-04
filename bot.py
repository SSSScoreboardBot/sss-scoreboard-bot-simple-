import os
import re
import json
import math
from datetime import datetime, timezone, timedelta

import praw

STOPWORDS_PATH = "tickers_stopwords.txt"

TICKER_RE = re.compile(r"(?<![A-Z0-9$])(\$?[A-Z]{1,5})(?![A-Z0-9])")


def load_config(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except Exception:
        return {}

def _dt_from_utc(ts: float) -> datetime:
    return datetime.fromtimestamp(ts, tz=timezone.utc)

def _within_hours(created_utc: float, hours: int) -> bool:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    return _dt_from_utc(created_utc) >= cutoff

def build_cross_sub_radar(r: praw.Reddit, cfg: dict, stopwords: set[str]) -> list[dict]:
    # Pull tickers from recent/high-engagement posts across selected subreddits.
    # We only parse title + selftext to keep API load low (no comment crawling).
    if not bool(cfg.get("cross_subs_enabled", False)):
        return []

    subs = cfg.get("cross_subs", [])
    max_out = int(cfg.get("cross_max_tickers", 8) or 8)

    agg_score: dict[str, float] = {}
    best_link: dict[str, tuple[float, str]] = {}  # (score, url)
    best_src: dict[str, str] = {}

    for s in subs:
        name = str(s.get("name", "")).strip()
        if not name:
            continue
        weight = float(s.get("weight", 0.35) or 0.35)
        mode = str(s.get("mode", "hot")).lower().strip()
        limit_posts = int(s.get("limit_posts", 40) or 40)
        lookback_hours = int(s.get("lookback_hours", 24) or 24)

        sub = r.subreddit(name)
        if mode == "new":
            it = sub.new(limit=limit_posts)
        elif mode == "top":
            # PRAW supports top(time_filter=...) for many installations.
            try:
                it = sub.top(time_filter="day", limit=limit_posts)
            except Exception:
                it = sub.hot(limit=limit_posts)
        else:
            it = sub.hot(limit=limit_posts)

        for post in it:
            try:
                if not _within_hours(post.created_utc, lookback_hours):
                    continue
            except Exception:
                continue

            title = getattr(post, "title", "") or ""
            body = getattr(post, "selftext", "") or ""
            txt = (title + "\n" + body).strip()
            tickers = set(extract_tickers(txt, stopwords))
            if not tickers:
                continue

            # Engagement proxy (bounded) to avoid one post dominating.
            score = float(getattr(post, "score", 0) or 0)
            com = float(getattr(post, "num_comments", 0) or 0)
            engagement = 1.0 + math.log1p(max(0.0, score)) + 0.5 * math.log1p(max(0.0, com))
            engagement = min(engagement, 12.0)

            url = "https://www.reddit.com" + (getattr(post, "permalink", "") or "")
            for t in tickers:
                inc = weight * engagement
                agg_score[t] = agg_score.get(t, 0.0) + inc
                prev = best_link.get(t)
                if prev is None or inc > prev[0]:
                    best_link[t] = (inc, url)
                    best_src[t] = f"r/{name}"

    ranked = sorted(agg_score.items(), key=lambda kv: (kv[1], kv[0]), reverse=True)[:max_out]
    out = []
    for t, sc in ranked:
        out.append({
            "ticker": t,
            "score": round(sc, 2),
            "best_post": best_link.get(t, (0.0, None))[1],
            "best_src": best_src.get(t, None),
        })
    return out
def _env_int(name: str, default: int) -> int:
    v = os.getenv(name, "")
    try:
        return int(v) if v.strip() != "" else default
    except Exception:
        return default

def _env_str(name: str, default: str) -> str:
    v = os.getenv(name, "")
    return v if v.strip() != "" else default

def load_stopwords() -> set[str]:
    sw = set()
    try:
        with open(STOPWORDS_PATH, "r", encoding="utf-8") as f:
            for line in f:
                t = line.strip().upper()
                if t and not t.startswith("#"):
                    sw.add(t)
    except FileNotFoundError:
        pass
    return sw

def is_candidate_ticker(raw: str, stopwords: set[str]) -> bool:
    t = raw.upper()
    # strip leading $
    if t.startswith("$"):
        t2 = t[1:]
        # allow 1-letter tickers only when written as $F, $T, etc.
        if len(t2) == 1:
            return True
        t = t2
    # reject 1-letter tickers unless $ prefixed
    if len(t) == 1:
        return False
    # reject stopwords/common tokens
    if t in stopwords:
        return False
    # reject purely vowels / weird patterns (rare)
    if t in {"AAAA", "BBBB", "CCCC"}:
        return False
    return True

def extract_tickers(text: str, stopwords: set[str]) -> list[str]:
    if not text:
        return []
    out = []
    for m in TICKER_RE.finditer(text.upper()):
        raw = m.group(1)
        if is_candidate_ticker(raw, stopwords):
            out.append(raw[1:] if raw.startswith("$") else raw)
    return out

def praw_client() -> praw.Reddit:
    return praw.Reddit(
        client_id=os.environ["REDDIT_CLIENT_ID"],
        client_secret=os.environ["REDDIT_CLIENT_SECRET"],
        username=os.environ["REDDIT_USERNAME"],
        password=os.environ["REDDIT_PASSWORD"],
        user_agent=os.environ["REDDIT_USER_AGENT"],
    )

def find_latest_daily_thread(subreddit: praw.models.Subreddit, title_prefix: str, lookback_hours: int):
    # Search newest posts that start with the prefix
    # We use .new() and filter locally (more reliable than search).
    cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
    for post in subreddit.new(limit=50):
        created = datetime.fromtimestamp(post.created_utc, tz=timezone.utc)
        if created < cutoff:
            break
        if post.title.strip().startswith(title_prefix):
            return post
    return None

def build_scoreboard(thread, stopwords: set[str], max_tickers: int):
    # Pull top-level comments
    thread.comments.replace_more(limit=0)
    top = thread.comments

    # score by unique author count per ticker
    ticker_authors: dict[str, set[str]] = {}
    ticker_best_comment: dict[str, tuple[int, str]] = {}  # (score, permalink)

    for c in top:
        if not hasattr(c, "body"):
            continue
        if c.author is None:
            continue
        author = str(c.author).lower()
        tickers = set(extract_tickers(c.body, stopwords))
        if not tickers:
            continue

        for t in tickers:
            ticker_authors.setdefault(t, set()).add(author)
            # track "best" top-level comment by score
            score = getattr(c, "score", 0) or 0
            link = "https://www.reddit.com" + getattr(c, "permalink", "")
            prev = ticker_best_comment.get(t)
            if prev is None or score > prev[0]:
                ticker_best_comment[t] = (score, link)

    ranked = sorted(ticker_authors.items(), key=lambda kv: (len(kv[1]), kv[0]), reverse=True)
    ranked = ranked[:max_tickers]

    items = []
    for t, authors in ranked:
        best = ticker_best_comment.get(t)
        best_link = best[1] if best else None
        items.append({
            "ticker": t,
            "unique_authors": len(authors),
            "best_comment": best_link
        })
    return items

def format_comment(items, hub_url: str, thread, cross_radar: list[dict]):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = []
    lines.append("Daily Scoreboard (Text MVP)")
    lines.append("")
    lines.append("Top tickers by unique authors mentioning them in this Daily Scanner thread (not financial advice).")
    lines.append(f"Updated: {ts}")
    lines.append("")

    if not items:
        lines.append("No tickers detected yet. Post in the format: TICKER - catalyst - invalidation - 1 data point.")
    else:
        for i, it in enumerate(items, start=1):
            t = it["ticker"]
            n = it["unique_authors"]
            best = it.get("best_comment")
            if best:
                lines.append(f"{i}. {t} — {n} unique posters — top comment: {best}")
            else:
                lines.append(f"{i}. {t} — {n} unique posters")


    # Cross-subreddit radar (optional)
    if cross_radar:
        lines.append("Viral radar (cross-subreddit, weighted):")
        for it in cross_radar:
            t = it["ticker"]
            sc = it.get("score", 0)
            src = it.get("best_src")
            link = it.get("best_post")
            if link and src:
                lines.append(f"- {t} — radar score {sc} — {src}: {link}")
            elif link:
                lines.append(f"- {t} — radar score {sc} — {link}")
            else:
                lines.append(f"- {t} — radar score {sc}")
        lines.append("")
    lines.append(f"Templates + rules (Hub): {hub_url}")
    return "\n".join(lines)

def main():
    subreddit_name = _env_str("SUBREDDIT", "ShortSqueezeStonks")
    hub_url = _env_str("HUB_URL", "https://www.reddit.com/r/ShortSqueezeStonks/s/RZJwT0l6wX")
    title_prefix = _env_str("THREAD_TITLE_PREFIX", "Daily Squeeze Scanner + Discussion")
    lookback_hours = _env_int("LOOKBACK_HOURS", 24)
    max_tickers = _env_int("MAX_TICKERS", 12)
    dry_run = _env_str("DRY_RUN", "").strip() == "1"

    stopwords = load_stopwords()
    cfg_path = _env_str("CONFIG_PATH", "config.json")
    cfg = load_config(cfg_path)

    r = praw_client()
    sub = r.subreddit(subreddit_name)

    thread = find_latest_daily_thread(sub, title_prefix, lookback_hours=48)
    if thread is None:
        raise SystemExit(f"Could not find a recent daily thread starting with: {title_prefix}")

    items = build_scoreboard(thread, stopwords, max_tickers=max_tickers)
    cross_radar = build_cross_sub_radar(r, cfg, stopwords)
    comment_body = format_comment(items, hub_url, thread, cross_radar)

    print("=== TARGET THREAD ===")
    print(thread.title)
    print("https://www.reddit.com" + thread.permalink)
    print("")
    print("=== COMMENT PREVIEW ===")
    print(comment_body)

    if dry_run:
        print("\nDRY_RUN=1 -> not posting.\n")
        return

    # Post as a top-level comment in the daily thread
    thread.reply(comment_body)
    print("\nPosted scoreboard comment successfully.\n")

if __name__ == "__main__":
    main()
