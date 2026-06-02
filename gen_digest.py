#!/usr/bin/env python3
"""Generate daily digest — parallel YouTube fetching with real duration filtering."""
from groq import Groq
from concurrent.futures import ThreadPoolExecutor, as_completed
import json, datetime, pathlib, urllib.request, xml.etree.ElementTree as ET
import re, os

DIGEST_DIR = pathlib.Path("digests")
DIGEST_DIR.mkdir(exist_ok=True)
date_str = datetime.date.today().isoformat()
MIN_DURATION_SEC = 480   # 8 minutes — filters out all shorts and short clips

YOUTUBE_HANDLES = [
    "@TBTGO", "@claude", "@OliurOnline", "@ScienceofScaling",
    "@ycombinator", "@talksatgoogle", "@aiDotEngineer", "@nischa",
    "@LennysPodcast", "@stanfordgsb", "@IBMTechnology", "@ILTB_Podcast",
    "@eoglobal", "@FrontRowSeat", "@anthropic-ai", "@starterstory",
    "@Harvardilab", "@SiliconValleyGirl", "@GregIsenberg",
]

RSS_FEEDS = [
    ("Hacker News",     "https://news.ycombinator.com/rss"),
    ("The Verge",       "https://www.theverge.com/rss/index.xml"),
    ("TechCrunch",      "https://techcrunch.com/feed/"),
    ("Ars Technica",    "https://feeds.arstechnica.com/arstechnica/index"),
    ("VentureBeat",     "https://venturebeat.com/feed/"),
    ("MIT Tech Review", "https://www.technologyreview.com/feed/"),
    ("Wired",           "https://www.wired.com/feed/rss"),
    ("IBM Blog",        "https://www.ibm.com/blog/feed/"),
]

HN_IBM_SEARCH = "https://hn.algolia.com/api/v1/search?query=IBM&tags=story&hitsPerPage=8"
HN_TOP        = "https://hacker-news.firebaseio.com/v0/topstories.json"
HN_ITEM       = "https://hacker-news.firebaseio.com/v0/item/{}.json"


# ── HTTP helper ───────────────────────────────────────────────────────────────
def fetch_url(url, timeout=12):
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": "Mozilla/5.0 DailyDigestBot/2.0"}
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", errors="replace")
    except Exception as e:
        print(f"  ✗ {url[:70]}: {e}")
        return None

def strip_html(text):
    return re.sub(r"<[^>]+>", " ", text or "").strip()


# ── Article fetching ──────────────────────────────────────────────────────────
def fetch_rss(source, url):
    raw = fetch_url(url)
    if not raw:
        return []
    items = []
    try:
        root = ET.fromstring(raw)
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        entries = root.findall(".//item") or root.findall("atom:entry", ns) or root.findall(".//entry")
        for e in entries[:6]:
            title = (e.findtext("title") or e.findtext("atom:title", namespaces=ns) or "").strip()
            link  = (e.findtext("link") or "").strip()
            if not link:
                el = e.find("{http://www.w3.org/2005/Atom}link") or e.find("link")
                link = (el.get("href", "") if el is not None else "").strip()
            if title and link:
                items.append({"title": title, "source": source, "url": link})
    except Exception as ex:
        print(f"  ✗ parse {source}: {ex}")
    return items

def fetch_hn_top(n=15):
    raw = fetch_url(HN_TOP)
    if not raw:
        return []
    items = []
    for sid in json.loads(raw)[:n]:
        d = fetch_url(HN_ITEM.format(sid))
        if not d:
            continue
        s = json.loads(d)
        if s.get("url") and s.get("title"):
            items.append({"title": s["title"], "source": "Hacker News", "url": s["url"]})
    return items

def fetch_hn_ibm():
    raw = fetch_url(HN_IBM_SEARCH)
    if not raw:
        return []
    try:
        hits = json.loads(raw).get("hits", [])
        return [{"title": h["title"], "source": "Hacker News (IBM)",
                 "url": h.get("url") or f"https://news.ycombinator.com/item?id={h.get('objectID')}"}
                for h in hits if h.get("title")]
    except:
        return []


# ── YouTube fetching ──────────────────────────────────────────────────────────
def resolve_channel(handle):
    """Returns (channel_id, channel_name) from a @handle page."""
    html = fetch_url(f"https://www.youtube.com/{handle}")
    if not html:
        return None, handle.lstrip("@")
    cid = None
    for pattern in [r'"channelId":"(UC[a-zA-Z0-9_-]{22})"',
                    r'"externalId":"(UC[a-zA-Z0-9_-]{22})"']:
        m = re.search(pattern, html)
        if m:
            cid = m.group(1)
            break
    # Channel name from page <title>: "Channel Name - YouTube"
    name_m = re.search(r'<title>([^<]+?)(?:\s*-\s*YouTube)?</title>', html)
    name = name_m.group(1).strip() if name_m else handle.lstrip("@")
    return cid, name

def get_channel_video_ids(cid):
    """Fetch RSS feed and return list of (vid_id, title) for latest videos."""
    raw = fetch_url(f"https://www.youtube.com/feeds/videos.xml?channel_id={cid}")
    if not raw:
        return []
    entries = []
    try:
        root = ET.fromstring(raw)
        ns = {"atom": "http://www.w3.org/2005/Atom",
              "yt":   "http://www.youtube.com/xml/schemas/2015"}
        for entry in root.findall("atom:entry", ns)[:8]:
            vid_id = (entry.findtext("yt:videoId", namespaces=ns) or "").strip()
            title  = (entry.findtext("atom:title",  namespaces=ns) or "").strip()
            if vid_id and title:
                entries.append((vid_id, title))
    except:
        pass
    return entries

def get_video_duration(vid_id):
    """Fetch video page and extract real duration in seconds. Returns None if unavailable."""
    page = fetch_url(f"https://www.youtube.com/watch?v={vid_id}", timeout=10)
    if not page:
        return None
    m = re.search(r'"lengthSeconds":"(\d+)"', page)
    return int(m.group(1)) if m else None

def fetch_all_youtube_videos():
    """
    1. Resolve all channel handles in parallel
    2. Fetch RSS feeds in parallel
    3. Fetch video durations in parallel
    4. Return only full-length videos (>= 8 min)
    """
    # Step 1: resolve handles → (cid, name)
    print("  Resolving channel IDs...")
    channels = {}
    with ThreadPoolExecutor(max_workers=10) as ex:
        futs = {ex.submit(resolve_channel, h): h for h in YOUTUBE_HANDLES}
        for f in as_completed(futs):
            handle = futs[f]
            cid, name = f.result()
            if cid:
                channels[cid] = name
            else:
                print(f"    ✗ {handle}: could not resolve")
    print(f"  {len(channels)} channels resolved")

    # Step 2: fetch RSS feeds in parallel → candidate video IDs
    candidates = []  # [(vid_id, title, channel_name)]
    with ThreadPoolExecutor(max_workers=10) as ex:
        futs = {ex.submit(get_channel_video_ids, cid): (cid, name)
                for cid, name in channels.items()}
        for f in as_completed(futs):
            cid, name = futs[f]
            for vid_id, title in f.result():
                candidates.append((vid_id, title, name))
    print(f"  {len(candidates)} candidate videos found")

    # Step 3: fetch durations in parallel, filter shorts
    print("  Checking video durations (filtering shorts)...")
    full_videos = []
    with ThreadPoolExecutor(max_workers=15) as ex:
        futs = {ex.submit(get_video_duration, vid_id): (vid_id, title, name)
                for vid_id, title, name in candidates}
        for f in as_completed(futs):
            vid_id, title, name = futs[f]
            duration = f.result()
            if duration is None:
                continue
            if duration < MIN_DURATION_SEC:
                continue  # skip shorts and short clips
            full_videos.append({
                "title":       title,
                "channel":     name,
                "url":         f"https://www.youtube.com/watch?v={vid_id}",
                "duration_min": round(duration / 60, 1),
            })
    print(f"  {len(full_videos)} full-length videos (≥8 min) after filtering")
    return full_videos


# ── Scrape everything ─────────────────────────────────────────────────────────
print("Fetching articles...")
rss_articles = []
for name, url in RSS_FEEDS:
    got = fetch_rss(name, url)
    print(f"  {name}: {len(got)}")
    rss_articles.extend(got)

print("Fetching HN top stories...")
hn_top = fetch_hn_top(15)
print(f"  {len(hn_top)} stories")

print("Searching HN for IBM...")
ibm_stories = fetch_hn_ibm()
print(f"  {len(ibm_stories)} IBM stories")

print("Fetching YouTube channels...")
all_videos = fetch_all_youtube_videos()


# ── Build prompt ──────────────────────────────────────────────────────────────
def fmt_articles(items):
    return "\n".join(f"• [{a['source']}] {a['title']} | {a['url']}" for a in items)

def fmt_videos(items):
    return "\n".join(
        f"• [{v['channel']}] {v['title']} | {v['duration_min']} min | {v['url']}"
        for v in items
    )

articles_block = fmt_articles((rss_articles + hn_top)[:15])
ibm_block      = fmt_articles(ibm_stories[:5])
videos_block   = fmt_videos(all_videos[:35])

fallback_note = ""
if not rss_articles and not hn_top:
    fallback_note = "NOTE: Live fetching failed. Use your knowledge of real recent articles with exact URLs (not homepages)."

PROMPT = f"""You are a personal daily content curator. Today is {date_str}.
{fallback_note}

## TECH ARTICLES
{articles_block or "(fetch failed)"}

## IBM STORIES (user writes about IBM on LinkedIn daily — always include 1)
{ibm_block or "(none — include 1 IBM story from your knowledge: watsonx, IBM Cloud, IBM Research, AI)"}

## YOUTUBE VIDEOS (all are full-length, durations shown)
{videos_block or "(fetch failed)"}

### Rules:
1. MORNING READ: 4-5 best articles. Prioritise AI, engineering, startups, IBM. Use EXACT URLs — no homepages.
2. GYM PLAYLIST: 4-6 videos, 30-50 min total. Use ONLY URLs from the list. Balance across Finance, Personal Growth, Technology. Pick substantive content: podcasts, talks, interviews, deep-dives. Use the real duration_min shown above.
3. One crisp sentence summary per item — what's the specific insight or takeaway.

Return ONLY valid JSON:
{{
  "morning": [{{"title": "...", "source": "...", "url": "...", "summary": "..."}}],
  "gym": [{{"title": "...", "channel": "...", "url": "...", "duration_min": 0.0, "category": "Finance|Personal Growth|Technology", "summary": "..."}}],
  "gym_total_min": 0,
  "mode": "live"
}}"""

# ── Call Groq ─────────────────────────────────────────────────────────────────
print("Calling Groq for curation...")
client = Groq(api_key=os.environ["GROQ_API_KEY"])
completion = client.chat.completions.create(
    model="llama-3.3-70b-versatile",
    messages=[{"role": "user", "content": PROMPT}],
    max_tokens=2000,
    response_format={"type": "json_object"},
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
    html       = html_path.read_text()
    digest_json = json.dumps(digest)
    marker     = "// Fallback: embedded data injected by the server or static build"
    lines      = [l for l in html.split("\n") if not l.strip().startswith("window.__DIGEST__")]
    new_lines  = []
    injected   = False
    for line in lines:
        if marker in line and not injected:
            new_lines.append(f"      window.__DIGEST__ = {digest_json};")
            injected = True
        new_lines.append(line)
    html_path.write_text("\n".join(new_lines))
    print("Injected digest into index.html")

# ── Print digest ──────────────────────────────────────────────────────────────
out = [
    "╔══════════════════════════════════════════════════════════════╗",
    f"║  DAILY DIGEST  ·  {date_str}  [live]                        ║",
    "╚══════════════════════════════════════════════════════════════╝\n",
    "☀  MORNING READ", "─" * 64,
]
for i, a in enumerate(digest.get("morning", []), 1):
    out += [f"{i}. {a['title']}", f"   {a['source']} → {a['url']}", f"   {a['summary']}\n"]

out += [f"\n🏋  GYM PLAYLIST  (~{digest.get('gym_total_min','?')} min)", "─" * 64]
for i, v in enumerate(digest.get("gym", []), 1):
    out += [f"{i}. {v['title']}", f"   {v['channel']} · {v['duration_min']} min · {v['category']}",
            f"   {v['url']}", f"   {v['summary']}\n"]

rendered = "\n".join(out)
(DIGEST_DIR / f"digest_{date_str}.txt").write_text(rendered)
print(rendered)
