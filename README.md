# Daily Digest

Your personal morning tech read + gym video playlist, curated by Claude every day.

## What it does

**Morning (~15 min):** 4–5 high-signal tech articles from the last 48 hours — AI, software, hardware, startups, open source.

**Gym (~30–40 min):** 4–6 YouTube videos balanced across Finance, Personal Growth, and Technology — from creators like Graham Stephan, Huberman Lab, Ali Abdaal, Fireship, and more.

Claude learns from your feedback (upvote/downvote) and improves picks over time.

---

## Quick start

### 1. Set your API key

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

### 2. Generate today's digest

```bash
python3 digest.py
```

Fetches live RSS feeds + YouTube, then uses Claude to curate and summarize.  
If network is unavailable, Claude generates from its own knowledge automatically.

### 3. Rate today's picks (after reading/watching)

```bash
python3 digest.py feedback
```

Upvote/downvote each article and video. Saved to `data/feedback.json` and shapes tomorrow's curation.

---

## Files

```
digest.py          # Main script — run this daily
data/
  feedback.json    # Your ratings (auto-created on first feedback run)
digests/
  digest_YYYY-MM-DD.json   # Raw digest data
  digest_YYYY-MM-DD.txt    # Human-readable output
```

## Automate it (crontab)

Run every morning at 7am:

```bash
crontab -e
# Add this line:
0 7 * * * cd /path/to/daily_digest && ANTHROPIC_API_KEY=sk-ant-... python3 digest.py >> /tmp/digest.log 2>&1
```

## How feedback shapes future digests

| Action | Effect |
|--------|--------|
| Upvote a source (e.g. TechCrunch) | Claude favors it in future digests |
| Downvote a source | Claude deprioritizes or avoids it |
| Upvote a video category | More Finance / Personal Growth / Technology |
| Downvote a category | Less of that category |

Feedback accumulates in `data/feedback.json`. The more you rate, the more personalized it gets.

## Data sources

**Articles:** Hacker News, The Verge, TechCrunch, Wired, MIT Technology Review, Ars Technica, VentureBeat

**YouTube creators include:** Graham Stephan, Andrei Jikh, Huberman Lab, Ali Abdaal, Matt D'Avella, Thomas Frank, Fireship, Theo (t3.gg), NetworkChuck, AI Explained
