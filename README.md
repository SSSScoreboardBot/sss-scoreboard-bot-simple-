# ShortSqueezeStonks Scoreboard Bot (A1 - Text MVP)

Goal: Post a lightweight daily "Top Tickers" scoreboard comment in the **Daily Squeeze Scanner + Discussion** thread.
- Pulls tickers from **top-level comments** in the latest daily thread (default: last 24h).
- Ranks by **unique authors mentioning** the ticker (reduces spam/repeat mentions).
- Adds "most upvoted comment link" per ticker (quick jump to the best writeup).
- Includes Hub link at the bottom for templates/rules.

This is the A1 Text MVP. Once you confirm ticker extraction quality, we can add A2: a clean WSB-style image render.

Hub (Pin #1 / templates + rules):
https://www.reddit.com/r/ShortSqueezeStonks/s/RZJwT0l6wX

## 1) Create a Reddit app (script)
Reddit -> User Settings -> Safety & Privacy -> **Developer Platform** -> "Create App".
- Type: **script**
- Redirect URI: http://localhost:8080 (any valid URL works for script apps)
- Note your **client_id** and **client_secret**.

## 2) Add GitHub Secrets (Repo -> Settings -> Secrets and variables -> Actions)
Required:
- REDDIT_CLIENT_ID
- REDDIT_CLIENT_SECRET
- REDDIT_USERNAME
- REDDIT_PASSWORD
- REDDIT_USER_AGENT   (example: "SSSScoreboardBot/1.0 by u/<yourbotusername>")
- SUBREDDIT           (example: "ShortSqueezeStonks")
Optional:
- HUB_URL             (defaults to Pin #1 above)
- THREAD_TITLE_PREFIX (default: "Daily Squeeze Scanner + Discussion")
- LOOKBACK_HOURS      (default: 24)
- MAX_TICKERS         (default: 12)
- DRY_RUN             ("1" to test without posting)

## 3) Enable GitHub Actions
- Commit these files to a new repo (or an existing one).
- Actions run on schedule (see workflow). You can also run manually (workflow_dispatch).

## 4) First test run (recommended)
Set DRY_RUN=1 in Secrets temporarily.
- Run the workflow manually.
- Check the Actions logs to confirm tickers look right.
Then set DRY_RUN back to empty/0.

## 5) Mod permissions
If you want the bot to **distinguish** its comment, sticky, or lock it:
- The bot account must be a mod and have the right perms.
This A1 bot only posts a comment (no sticky/lock) by default.

## Notes / Safety
- Not financial advice. This is a community organizing tool.
- Ticker extraction is conservative: avoids 1-letter tickers unless written as $F, $T, etc.
- We maintain a stopword list to prevent false positives (e.g., "DD", "ER", "CEO").

## Optional: Viral radar (cross-subreddit)

This bot can optionally add a small "Viral radar" section sourced from recent posts in other subreddits (ex: r/wallstreetbets, r/Shortsqueeze, r/pennystocks).
It does **not** crawl comments for these external subs (title + selftext only) to keep API usage light.

How to enable:
1) Copy `config.example.json` to `config.json`
2) Set `"cross_subs_enabled": true`
3) Edit the `cross_subs` list (names + weights)
4) Set env var `CONFIG_PATH=config.json` (default)

Guardrail suggestion:
- Keep weights < 0.6 for big subs so they don't dominate your community signal.
