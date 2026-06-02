#!/usr/bin/env python3
"""Generate daily digest from real scraped articles and YouTube channel feeds."""
from groq import Groq
import json, datetime, pathlib, urllib.request, xml.etree.ElementTree as ET
import re, os

DIGEST_DIR = pathlib.Path("digests")
DIGEST_DIR.mkdir(exist_ok=True)
date_str = datetime.date.today().isoformat()

# ── YouTube channel handles (resolved to IDs at runtime) ─────────────────────
YOUTUBE_HANDLES = [
    "@TBTGO",
    "@claude",
    "@OliurOnline",
    "@ScienceofScaling",
    "@ycombinator",
    "@talksatgoogle",
    "@aiDotEngineer",
    "@nischa",
    "@LennysPodcast",
    "@stanfordgsb",
    "@IBMTechnology",
    "@ILTB_Podcast",
    "@eoglobal",
    "@FrontRowSeat",
    "@anthropic-ai",
    "@starterstory",
    "@Harvardilab",
    "@SiliconValleyGirl",
    "@GregIsenberg",
]

# ── RSS article feeds ─────────────────────────────────────────────────────────
RSS_FEEDS = [
    ("Hacker News",       "https://news.ycombinator.com/rss"),
    ("The Verge",         "https://www.theverge.com/rss/index.xml"),
    ("TechCrunch",        "https://techcrunch.com/feed/"),
    ("Ars Technica",      "https://feeds.arstechnica.com/arstechnica/index"),
    ("VentureBeat",       "https://venturebeat.com/feed/"),
    ("MIT Tech Review",   "https://www.technologyreview.com/feed/"),
    ("Wired",             "https://www.wired.com/feed/rss"),
    ("IBM Blog",          "https://www.ibm.com/blog/feed/"),
    ("IBM Research",      "https://research.ibm.com/feed.xml"),
]

HN_IBM_SEARCH = "https://hn.algolia.com/api/v1/search?query=IBM&tags=story&hitsPerPage=8"
HN_TOP        = "https://hacker-news.firebaseio.com/v0/topstories.json"
HN_ITEM       = "https://hacker-news.firebaseio.com/v0/item/{}.json"


def fetch_url(url, timeout=12):
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": "Mozilla/5.0 DailyDigestBot/2.0"}
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", errors="replace")
    except Exception as e:
        print(f"  ✗ {url[:60]}: {e}")
        return None


def strip_html(text):
    return re.sub(r"<[^>]+>", " ", text or "").strip()


def fetch_rss(source, url):
    raw = fetch_url(url)
    if not raw:
        return []
    items = []
    try:
        root = ET.fromstring(raw)
        ns = {"atom": "http://www.w3.org/2005/Atom",
              "media": "http://search.yahoo.com/mrss/"}
        entries = root.findall(".//item") or \
                  root.findall("atom:entry", ns) or \
                  root.findall(".//entry")
        for e in entries[:6]:
            title = (e.findtext("title") or e.findtext("atom:title", namespaces=ns) or "").strip()
            link  = (e.findtext("link")  or "").strip()
            if not link:
                el = e.find("{http://www.w3.org/2005/Atom}link") or e.find("link")
                link = (el.get("href","") if el is not None else "").strip()
            desc = strip_html(
                e.findtext("description") or
                e.findtext("{http://www.w3.org/2005/Atom}summary") or ""
            )[:250]
            if title and link:
                items.append({"title": title, "source": source, "url": link, "snippet": desc})
    except Exception as ex:
        print(f"  ✗ parse {source}: {ex}")
    return items


def fetch_hn_top(n=10):
    raw = fetch_url(HN_TOP)
    if not raw:
        return []
    ids = json.loads(raw)[:n]
    items = []
    for sid in ids:
        d = fetch_url(HN_ITEM.format(sid))
        if not d:
            continue
        story = json.loads(d)
        if story.get("url") and story.get("title"):
            items.append({"title": story["title"], "source": "Hacker News",
                          "url": story["url"], "snippet": ""})
    return items


def fetch_hn_ibm():
    raw = fetch_url(HN_IBM_SEARCH)
    if not raw:
        return []
    try:
        hits = json.loads(raw).get("hits", [])
        return [{"title": h.get("title",""), "source": "Hacker News (IBM)",
                 "url": h.get("url") or f"https://news.ycombinator.com/item?id={h.get('objectID')}",
                 "snippet": ""} for h in hits if h.get("title")]
    except:
        return []


def resolve_channel_id(handle):
    """Fetch a YouTube channel page and extract its UC... channel ID."""
    html = fetch_url(f"https://www.youtube.com/{handle}")
    if not html:
        return None, handle.lstrip("@")
    match = re.search(r'"channelId":"(UC[a-zA-Z0-9_-]{22})"', html)
    if not match:
        match = re.search(r'"externalId":"(UC[a-zA-Z0-9_-]{22})"', html)
    name_match = re.search(r'"title":"([^"]{1,60})"', html)
    name = name_match.group(1) if name_match else handle.lstrip("@")
    return (match.group(1) if match else None), name


def is_short(title, desc, vid_id):
    """Return True if the video is a YouTube Short (skip these)."""
    combined = (title + " " + desc).lower()
    if "#short" in combined or "#ytshort" in combined:
        return True
    # Verify via YouTube: shorts redirect to /shorts/ path
    page = fetch_url(f"https://www.youtube.com/watch?v={vid_id}")
    if page and f'/shorts/{vid_id}' in page:
        return True
    return False


def fetch_youtube_channel(name, cid):
    url = f"https://www.youtube.com/feeds/videos.xml?channel_id={cid}"
    raw = fetch_url(url)
    if not raw:
        return []
    videos = []
    try:
        root = ET.fromstring(raw)
        ns = {"atom":  "http://www.w3.org/2005/Atom",
              "media": "http://search.yahoo.com/mrss/",
              "yt":    "http://www.youtube.com/xml/schemas/2015"}
        for entry in root.findall("atom:entry", ns)[:6]:  # check more to account for skipped shorts
            title  = (entry.findtext("atom:title",   namespaces=ns) or "").strip()
            vid_id = (entry.findtext("yt:videoId",   namespaces=ns) or "").strip()
            desc_el = entry.find("media:group/media:description", ns)
            desc   = strip_html(desc_el.text if desc_el is not None else "")[:200]
            if title and vid_id:
                if is_short(title, desc, vid_id):
                    print(f"    ↷ skipping short: {title[:50]}")
                    continue
                videos.append({"title": title, "channel": name,
                                "url": f"https://www.youtube.com/watch?v={vid_id}",
                                "snippet": desc})
    except Exception as e:
        print(f"  ✗ YT parse {name}: {e}")
    return videos


# ── Scrape ────────────────────────────────────────────────────────────────────
print("Fetching HN top stories...")
hn_top = fetch_hn_top(15)
print(f"  {len(hn_top)} stories")

print("Fetching RSS feeds...")
rss_articles = []
for name, url in RSS_FEEDS:
    got = fetch_rss(name, url)
    print(f"  {name}: {len(got)} articles")
    rss_articles.extend(got)

print("Searching HN for IBM...")
ibm_stories = fetch_hn_ibm()
print(f"  {len(ibm_stories)} IBM stories")

print("Fetching YouTube channels...")
all_videos = []
for handle in YOUTUBE_HANDLES:
    cid, name = resolve_channel_id(handle)
    if not cid:
        print(f"  {handle}: could not resolve channel ID")
        continue
    got = fetch_youtube_channel(name, cid)
    print(f"  {handle} ({name}): {len(got)} videos")
    all_videos.extend(got)

# ── Build prompt ──────────────────────────────────────────────────────────────
def fmt_articles(items):
    return "\n".join(f"• [{a['source']}] {a['title']} | {a['url']}" for a in items)

def fmt_videos(items):
    return "\n".join(f"• [{v['channel']}] {v['title']} | {v['url']}" for v in items)

# Keep prompt small: top 15 articles + 5 IBM + all videos (titles only)
articles_block = fmt_articles((rss_articles + hn_top)[:15])
ibm_block      = fmt_articles(ibm_stories[:5])
videos_block   = fmt_videos(all_videos)

fallback_note = ""
if not rss_articles and not hn_top:
    fallback_note = "NOTE: Live fetching failed. Use your knowledge of recent (last 7 days) tech stories with real publisher URLs (not homepages)."

PROMPT = f"""You are a personal daily content curator. Today is {date_str}.

{fallback_note}

## REAL TECH ARTICLES FETCHED TODAY
{articles_block or "(fetch failed — see fallback note)"}

## IBM-SPECIFIC STORIES (user writes about IBM on LinkedIn daily)
{ibm_block or "(none fetched — include 1 real IBM story: watsonx, IBM Cloud, IBM Research, consulting, or AI)"}

## REAL YOUTUBE VIDEOS FROM SUBSCRIBED CHANNELS
{videos_block or "(fetch failed — see fallback note)"}

### Curation rules:
1. MORNING READ: pick the 4-5 most insightful, specific articles. Prioritise AI breakthroughs, engineering depth, startup funding, and IBM. Always include at least 1 IBM item. Use the EXACT URLs from the list above — never use a homepage URL like techcrunch.com.
2. GYM PLAYLIST: pick 4-6 videos totalling 30-45 min. Balance: 2 Finance, 2 Personal Growth, 2 Technology. Use ONLY URLs from the list above — never invent a YouTube URL. ONLY pick full-length videos (podcasts, talks, interviews, tutorials — minimum 8 minutes). NEVER pick YouTube Shorts or clips under 3 minutes. Estimate realistic durations (10–40 min) based on the content type.
3. Summaries must be one crisp sentence explaining the specific insight or takeaway.

Return ONLY valid JSON, no markdown fences:
{{
  "morning": [
    {{"title": "...", "source": "...", "url": "EXACT URL FROM LIST", "summary": "One sentence."}}
  ],
  "gym": [
    {{"title": "...", "channel": "...", "url": "https://www.youtube.com/watch?v=REAL_ID",
     "duration_min": 12.5, "category": "Finance|Personal Growth|Technology",
     "summary": "One sentence."}}
  ],
  "gym_total_min": 37,
  "mode": "live"
}}"""

# ── Call Groq ─────────────────────────────────────────────────────────────────
print("Calling Groq for curation...")
client = Groq(api_key=os.environ["GROQ_API_KEY"])
completion = client.chat.completions.create(
    model="llama-3.3-70b-versatile",
    messages=[{"role": "user", "content": PROMPT}],
    max_tokens=2000,
)

raw = completion.choices[0].message.content.strip()
if raw.startswith("```"):
    raw = "\n".join(raw.split("\n")[1:]).rsplit("```", 1)[0]

digest = json.loads(raw)

# ── Save JSON ─────────────────────────────────────────────────────────────────
(DIGEST_DIR / f"digest_{date_str}.json").write_text(json.dumps(digest, indent=2))

# ── Inject into index.html ────────────────────────────────────────────────────
html_path = pathlib.Path("index.html")
if html_path.exists():
    html = html_path.read_text()
    digest_json = json.dumps(digest)
    marker = "// Fallback: embedded data injected by the server or static build"
    lines = html.split("\n")
    # Remove all existing window.__DIGEST__ lines, then insert before marker
    lines = [l for l in lines if not l.strip().startswith("window.__DIGEST__")]
    new_lines = []
    injected = False
    for line in lines:
        if marker in line and not injected:
            new_lines.append(f"      window.__DIGEST__ = {digest_json};")
            injected = True
        new_lines.append(line)
    html_path.write_text("\n".join(new_lines))
    print("Injected digest into index.html")

# ── Render text ───────────────────────────────────────────────────────────────
out = []
out.append("╔══════════════════════════════════════════════════════════════╗")
out.append(f"║  DAILY DIGEST  ·  {date_str}  [{digest.get('mode','live')}]              ║")
out.append("╚══════════════════════════════════════════════════════════════╝\n")
out.append("☀  MORNING READ  (~15 min)")
out.append("─" * 64)
for i, a in enumerate(digest.get("morning", []), 1):
    out.append(f"{i}. {a['title']}")
    out.append(f"   Source : {a['source']}")
    out.append(f"   Link   : {a['url']}")
    out.append(f"   Why    : {a['summary']}\n")

total = digest.get("gym_total_min", "?")
out.append(f"🏋  GYM PLAYLIST  (~{total} min)")
out.append("─" * 64)
for i, v in enumerate(digest.get("gym", []), 1):
    out.append(f"{i}. {v['title']}")
    out.append(f"   Channel  : {v['channel']}")
    out.append(f"   Duration : {v['duration_min']} min  |  {v['category']}")
    out.append(f"   Link     : {v['url']}")
    out.append(f"   Learn    : {v['summary']}\n")

out.append("─" * 64)
out.append("Rate today's picks → run:  python3 digest.py feedback\n")
rendered = "\n".join(out)
(DIGEST_DIR / f"digest_{date_str}.txt").write_text(rendered)
print(rendered)
