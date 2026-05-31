#!/usr/bin/env python3
"""One-off script to generate today's digest using Claude's knowledge."""
import anthropic, json, datetime, pathlib

DIGEST_DIR = pathlib.Path("digests")
DIGEST_DIR.mkdir(exist_ok=True)

client = anthropic.Anthropic()
date_str = datetime.date.today().isoformat()

PROMPT = """You are a personal daily content curator. Today is 2026-05-31.

Generate a high-quality daily digest using your knowledge of recent real content.

### 1. MORNING TECH READ (~15 min)
Pick 4-5 real articles/posts from the last week across:
- AI/LLMs (model releases, research, agentic AI, tools)
- Software engineering (frameworks, dev tools, languages)
- Hardware / chips / infrastructure
- Startups / VC funding
- Cybersecurity or open source

Use real URLs where you know them confidently; otherwise use the publication's homepage.

### 2. GYM PLAYLIST (~30-40 min total)
Pick 4-6 real YouTube videos (8-30 min each) from well-known creators:
- Finance: Graham Stephan, Andrei Jikh, Two Cents, The Plain Bagel, Minority Mindset, Erin Talks Money
- Personal Growth: Huberman Lab, Ali Abdaal, Matt D'Avella, Thomas Frank
- Technology/AI: Fireship, Theo (t3.gg), NetworkChuck, AI Explained, Andrej Karpathy

Target total: 30-40 min. Pick real, specific videos.

Return ONLY valid JSON with no markdown fences:
{
  "morning": [
    {"title": "...", "source": "...", "url": "...", "summary": "One sentence why it matters."}
  ],
  "gym": [
    {"title": "...", "channel": "...", "url": "https://www.youtube.com/watch?v=...",
     "duration_min": 12.5, "category": "Finance|Personal Growth|Technology",
     "summary": "One sentence what you learn."}
  ],
  "gym_total_min": 37,
  "mode": "ai-curated"
}"""

response = client.messages.create(
    model="claude-sonnet-4-6",
    max_tokens=2500,
    messages=[{"role": "user", "content": PROMPT}],
)

raw = response.content[0].text.strip()
if raw.startswith("```"):
    lines = raw.split("\n")
    raw = "\n".join(lines[1:]).rsplit("```", 1)[0]

digest = json.loads(raw)

(DIGEST_DIR / f"digest_{date_str}.json").write_text(json.dumps(digest, indent=2))

out = []
out.append("╔══════════════════════════════════════════════════════════════╗")
out.append(f"║  DAILY DIGEST  ·  {date_str}  [AI-curated]              ║")
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
