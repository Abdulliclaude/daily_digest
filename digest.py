#!/usr/bin/env python3
"""Daily digest generator: morning tech reads + gym video playlist."""

import json
import sys
import datetime
import subprocess
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
import anthropic

DATA_DIR   = Path(__file__).parent / "data"
DIGEST_DIR = Path(__file__).parent / "digests"
FEEDBACK_FILE = DATA_DIR / "feedback.json"

DATA_DIR.mkdir(exist_ok=True)
DIGEST_DIR.mkdir(exist_ok=True)

TECH_FEEDS = [
    ("Hacker News",     "https://news.ycombinator.com/rss"),
    ("The Verge",       "https://www.theverge.com/rss/index.xml"),
    ("TechCrunch",      "https://techcrunch.com/feed/"),
    ("Wired",           "https://www.wired.com/feed/rss"),
    ("MIT Tech Review", "https://www.technologyreview.com/feed/"),
    ("Ars Technica",    "https://feeds.arstechnica.com/arstechnica/index"),
    ("VentureBeat",     "https://feeds.feedburner.com/venturebeat/SZYF"),
]

GYM_QUERIES = [
    "financial independence investing explained 2025",
    "personal finance tips beginners",
    "personal growth mindset podcast",
    "productivity habits high performers",
    "AI artificial intelligence explained 2025",
    "software engineering career advice",
    "startup lessons entrepreneurship",
]


def fetch_rss(source_name: str, url: str) -> list[dict]:
    items = []
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "DailyDigest/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            content = resp.read()
        root = ET.fromstring(content)
        ns = {"atom": "http://www.w3.org/2005/Atom"}

        for item in root.findall(".//item"):
            title = (item.findtext("title") or "").strip()
            link  = (item.findtext("link") or "").strip()
            pub   = item.findtext("pubDate") or ""
            desc  = (item.findtext("description") or "").strip()[:300]
            if title and link:
                items.append({"title": title, "url": link, "source": source_name,
                               "published": pub, "snippet": desc})

        for entry in root.findall("atom:entry", ns):
            title   = (entry.findtext("atom:title", namespaces=ns) or "").strip()
            link_el = entry.find("atom:link", ns)
            link    = (link_el.get("href") if link_el is not None else "") or ""
            pub     = entry.findtext("atom:updated", namespaces=ns) or ""
            desc    = (entry.findtext("atom:summary", namespaces=ns) or "").strip()[:300]
            if title and link:
                items.append({"title": title, "url": link, "source": source_name,
                               "published": pub, "snippet": desc})
    except Exception:
        pass
    return items[:10]


def search_youtube(query: str, max_results: int = 3) -> list[dict]:
    videos = []
    try:
        cmd = [
            "yt-dlp", f"ytsearch{max_results}:{query}",
            "--print", "%(id)s\t%(title)s\t%(channel)s\t%(duration)s\t%(view_count)s",
            "--no-warnings", "--quiet", "--skip-download",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        for line in result.stdout.strip().splitlines():
            parts = line.split("\t")
            if len(parts) >= 4:
                vid_id, title, channel = parts[0], parts[1], parts[2]
                duration = int(parts[3]) if parts[3].isdigit() else 0
                views    = int(parts[4]) if len(parts) > 4 and parts[4].isdigit() else 0
                if 480 <= duration <= 2700 and views >= 10000:
                    videos.append({
                        "title": title, "channel": channel,
                        "url": f"https://www.youtube.com/watch?v={vid_id}",
                        "duration_min": round(duration / 60, 1),
                        "views": views, "query_tag": query,
                    })
    except Exception:
        pass
    return videos


def load_feedback() -> dict:
    if FEEDBACK_FILE.exists():
        return json.loads(FEEDBACK_FILE.read_text())
    return {"upvoted_sources": {}, "downvoted_sources": {}, "upvoted_tags": {}, "downvoted_tags": {}}


def save_feedback(fb: dict):
    FEEDBACK_FILE.write_text(json.dumps(fb, indent=2))


def curate_live(articles: list[dict], videos: list[dict], feedback: dict) -> dict:
    """Curate from live-fetched data."""
    client = anthropic.Anthropic()
    prompt = f"""You are a personal content curator. Today is {datetime.date.today()}.

Select content for TWO digest sections:

### 1. MORNING TECH READ (~15 min)
Pick 4–5 articles. Prefer: AI breakthroughs, major launches, funding rounds, hardware, dev tools.
Boost sources the user upvoted; avoid downvoted sources.

### 2. GYM PLAYLIST (~30–40 min total)
Pick 4–6 YouTube videos. Balance: Finance / Personal Growth / Technology.
Prefer higher view counts. Total duration 30–40 min.

## User Feedback History
{json.dumps(feedback, indent=2)}

## Available Articles
{json.dumps(articles[:40], indent=2)}

## Available Videos
{json.dumps(videos[:30], indent=2)}

Return ONLY valid JSON (no markdown fences):
{{
  "morning": [
    {{"title": "...", "source": "...", "url": "...", "summary": "One sentence why it matters."}}
  ],
  "gym": [
    {{"title": "...", "channel": "...", "url": "...", "duration_min": 12.5,
      "category": "Finance|Personal Growth|Technology", "summary": "One sentence what you learn."}}
  ],
  "gym_total_min": 37,
  "mode": "live"
}}"""

    response = client.messages.create(
        model="claude-sonnet-4-6", max_tokens=2000,
        messages=[{"role": "user", "content": prompt}],
    )
    return _parse_json(response.content[0].text)


def curate_from_knowledge(feedback: dict) -> dict:
    """Generate digest from Claude's knowledge when live feeds are unavailable."""
    client = anthropic.Anthropic()
    upvoted   = feedback.get("upvoted_sources", {})
    downvoted = feedback.get("downvoted_sources", {})

    prompt = f"""You are a personal daily content curator. Today is {datetime.date.today()}.

Live RSS feeds are unavailable, so generate a digest using your knowledge of recent tech news and well-regarded YouTube content.

### 1. MORNING TECH READ (~15 min)
Generate 4–5 real, specific articles or posts from the past week across:
- AI / LLMs (model releases, research, tools)
- Software engineering (frameworks, languages, tools)
- Hardware / chips
- Startups / VC funding
- Cybersecurity or open source

For each, provide the actual URL if you know it with high confidence; otherwise use the publication's homepage.
Preferred sources (user upvoted): {list(upvoted.keys()) or 'none yet'}
Avoid (user downvoted): {list(downvoted.keys()) or 'none'}

### 2. GYM PLAYLIST (~30–40 min total)
Recommend 4–6 real YouTube videos/episodes (8–30 min each) from well-known creators across:
- **Finance**: e.g. Graham Stephan, Andrei Jikh, Two Cents, The Plain Bagel, Minority Mindset
- **Personal Growth**: e.g. Lex Fridman, Huberman Lab, Matt D'Avella, Ali Abdaal, Thomas Frank
- **Technology / AI**: e.g. Fireship, Theo - t3.gg, NetworkChuck, TechLinked, AI Explained

Target total: 30–40 min. Pick specific real videos you know about.

Return ONLY valid JSON (no markdown fences, no commentary):
{{
  "morning": [
    {{"title": "...", "source": "Publication Name", "url": "https://...", "summary": "One sentence why it matters."}}
  ],
  "gym": [
    {{"title": "...", "channel": "...", "url": "https://www.youtube.com/watch?v=...",
      "duration_min": 12.5, "category": "Finance|Personal Growth|Technology",
      "summary": "One sentence what you learn."}}
  ],
  "gym_total_min": 37,
  "mode": "ai-curated"
}}"""

    response = client.messages.create(
        model="claude-sonnet-4-6", max_tokens=2500,
        messages=[{"role": "user", "content": prompt}],
    )
    return _parse_json(response.content[0].text)


def _parse_json(raw: str) -> dict:
    raw = raw.strip()
    if raw.startswith("```"):
        lines = raw.split("\n")
        raw = "\n".join(lines[1:])
        raw = raw.rsplit("```", 1)[0]
    return json.loads(raw)


def render_digest(digest: dict, date_str: str) -> str:
    mode_label = " [AI-curated]" if digest.get("mode") == "ai-curated" else ""
    lines = []
    lines.append("╔══════════════════════════════════════════════════════════════╗")
    lines.append(f"║  DAILY DIGEST  ·  {date_str}{mode_label:<{43 - len(date_str)}}║")
    lines.append("╚══════════════════════════════════════════════════════════════╝\n")

    lines.append("☀  MORNING READ  (~15 min)")
    lines.append("─" * 64)
    for i, a in enumerate(digest.get("morning", []), 1):
        lines.append(f"{i}. {a['title']}")
        lines.append(f"   Source : {a['source']}")
        lines.append(f"   Link   : {a['url']}")
        lines.append(f"   Why    : {a['summary']}\n")

    total = digest.get("gym_total_min", "?")
    lines.append(f"🏋  GYM PLAYLIST  (~{total} min)")
    lines.append("─" * 64)
    for i, v in enumerate(digest.get("gym", []), 1):
        lines.append(f"{i}. {v['title']}")
        lines.append(f"   Channel  : {v['channel']}")
        lines.append(f"   Duration : {v['duration_min']} min  |  {v['category']}")
        lines.append(f"   Link     : {v['url']}")
        lines.append(f"   Learn    : {v['summary']}\n")

    lines.append("─" * 64)
    lines.append("Rate today's picks → run:  python3 digest.py feedback\n")
    return "\n".join(lines)


def collect_feedback_interactive(digest: dict):
    fb = load_feedback()
    print("\n📊 Rate today's articles (u=upvote  d=downvote  s=skip):\n")
    for item in digest.get("morning", []):
        src = item["source"]
        c = input(f"  [{src}] {item['title'][:60]}…  (u/d/s): ").strip().lower()
        if c == "u":
            fb["upvoted_sources"][src] = fb["upvoted_sources"].get(src, 0) + 1
        elif c == "d":
            fb["downvoted_sources"][src] = fb["downvoted_sources"].get(src, 0) + 1

    print("\n📊 Rate today's videos:\n")
    for item in digest.get("gym", []):
        cat = item["category"]
        c = input(f"  [{cat}] {item['title'][:55]}…  (u/d/s): ").strip().lower()
        if c == "u":
            fb["upvoted_tags"][cat] = fb["upvoted_tags"].get(cat, 0) + 1
        elif c == "d":
            fb["downvoted_tags"][cat] = fb["downvoted_tags"].get(cat, 0) + 1

    save_feedback(fb)
    print("\n✅ Feedback saved — tomorrow's digest will improve.\n")


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "generate"
    date_str    = datetime.date.today().isoformat()
    digest_path = DIGEST_DIR / f"digest_{date_str}.json"
    text_path   = DIGEST_DIR / f"digest_{date_str}.txt"

    if mode == "feedback":
        if not digest_path.exists():
            print("No digest found for today. Run without arguments first.")
            sys.exit(1)
        collect_feedback_interactive(json.loads(digest_path.read_text()))
        return

    # ── Try live data first ──────────────────────────────────────────────────
    print(f"🔍 Fetching tech articles from {len(TECH_FEEDS)} sources…")
    articles = []
    for name, url in TECH_FEEDS:
        fetched = fetch_rss(name, url)
        articles.extend(fetched)
        status = f"{len(fetched)} items" if fetched else "unavailable"
        print(f"   {name}: {status}")

    print(f"\n📺 Searching YouTube ({len(GYM_QUERIES)} queries)…")
    videos = []
    for q in GYM_QUERIES:
        found = search_youtube(q, max_results=3)
        videos.extend(found)
        status = f"{len(found)} videos" if found else "unavailable"
        print(f"   '{q[:50]}': {status}")

    seen: set = set()
    videos = [v for v in videos if not (v["url"] in seen or seen.add(v["url"]))]

    feedback = load_feedback()

    if articles or videos:
        print(f"\n🤖 Curating with Claude ({len(articles)} articles, {len(videos)} videos)…")
        digest = curate_live(articles, videos, feedback)
    else:
        print("\n🤖 Live feeds unavailable — generating digest from Claude's knowledge…")
        digest = curate_from_knowledge(feedback)

    digest_path.write_text(json.dumps(digest, indent=2))
    rendered = render_digest(digest, date_str)
    text_path.write_text(rendered)

    print("\n" + rendered)
    print(f"💾 Saved to {text_path}")


if __name__ == "__main__":
    main()
