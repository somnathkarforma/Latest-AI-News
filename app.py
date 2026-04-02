from __future__ import annotations

import json
import os
import re
import textwrap
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from html import escape, unescape
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus, urlparse
from urllib.request import Request, urlopen

try:
    import google.generativeai as genai
except Exception:
    genai = None

try:
    from tavily import TavilyClient
except Exception:
    TavilyClient = None

OUTPUT_FILE = Path("index.html")
MAX_ARTICLES = int(os.getenv("MAX_ARTICLES", "8"))
QUERY = (
    "latest AI developments, model releases, benchmarks, enterprise adoption, "
    "funding, policy updates and product launches from the last 48 hours"
)
USER_AGENT = "Mozilla/5.0 (compatible; Latest-AI-News/1.0)"


def fetch_tavily_articles() -> tuple[list[dict[str, str]], str]:
    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        return [], "Tavily API key not configured"
    if TavilyClient is None:
        return [], "tavily-python package not installed"

    client = TavilyClient(api_key=api_key)
    response = client.search(
        query=QUERY,
        topic="news",
        days=2,
        search_depth="advanced",
        include_raw_content=True,
        max_results=MAX_ARTICLES,
    )

    articles: list[dict[str, str]] = []
    for item in response.get("results", []):
        url = item.get("url", "")
        source = item.get("source") or urlparse(url).netloc.replace("www.", "") or "Unknown source"
        articles.append(
            {
                "title": item.get("title") or "Untitled article",
                "url": url,
                "source": source,
                "summary": item.get("content") or item.get("raw_content") or "",
                "published": item.get("published_date") or "",
            }
        )
    return articles[:MAX_ARTICLES], "Tavily"


def fetch_google_news_rss() -> tuple[list[dict[str, str]], str]:
    url = (
        "https://news.google.com/rss/search?q="
        f"{quote_plus('AI news when:2d')}&hl=en-US&gl=US&ceid=US:en"
    )
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=20) as response:
        xml_data = response.read()

    root = ET.fromstring(xml_data)
    articles: list[dict[str, str]] = []
    for item in root.findall(".//item")[:MAX_ARTICLES]:
        raw_title = (item.findtext("title") or "Untitled article").strip()
        title, source = raw_title, "Google News"
        if " - " in raw_title:
            title, source = raw_title.rsplit(" - ", 1)

        articles.append(
            {
                "title": title.strip(),
                "url": (item.findtext("link") or "").strip(),
                "source": source.strip(),
                "summary": clean_text(item.findtext("description") or "", 280),
                "published": (item.findtext("pubDate") or "").strip(),
            }
        )
    return articles, "Google News RSS"


def collect_articles() -> tuple[list[dict[str, str]], str, list[str]]:
    notes: list[str] = []

    for fetcher in (fetch_tavily_articles, fetch_google_news_rss):
        try:
            articles, label = fetcher()
            if articles:
                return articles, label, []
            notes.append(label)
        except Exception as exc:  # pragma: no cover - network failures are environment-specific
            notes.append(f"{fetcher.__name__} failed: {exc}")

    return [], "Offline fallback", notes


def _extract_json_blob(text: str) -> dict[str, Any] | None:
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        return None

    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


def summarize_with_gemini(articles: list[dict[str, str]]) -> dict[str, Any] | None:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key or genai is None or not articles:
        return None

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(os.getenv("GEMINI_MODEL", "gemini-1.5-flash"))

    prompt = textwrap.dedent(
        f"""
        You are preparing a compact daily AI news dashboard from the last 48 hours.
        Return STRICT JSON only with this schema:
        {{
          "lead": "Two-sentence overview.",
          "highlights": ["3 to 5 concise bullets with concrete details"],
          "watchlist": ["2 to 4 forward-looking items to watch next"],
          "stats": [
            {{"label": "Stories reviewed", "value": "8"}},
            {{"label": "Dominant theme", "value": "Model launches"}}
          ]
        }}

        Articles:
        {json.dumps(articles[:MAX_ARTICLES], ensure_ascii=False)}
        """
    ).strip()

    response = model.generate_content(prompt)
    text = getattr(response, "text", "") or ""
    return _extract_json_blob(text)


def build_fallback_summary(
    articles: list[dict[str, str]], source_label: str, notes: list[str]
) -> dict[str, Any]:
    if articles:
        highlights = [
            f"{article['title']} — {clean_text(article['summary'] or article['source'], 140)}"
            for article in articles[:5]
        ]
        lead = (
            f"{len(articles)} recent AI stories were collected from {source_label}. "
            "Add a Gemini API key to turn the headlines into a richer automated briefing."
        )
    else:
        highlights = [
            "The site scaffold is ready, but this run could not fetch live news.",
            "Add API keys and rerun the workflow to publish a populated dashboard.",
        ]
        lead = (
            "The automation is set up and waiting for live data sources. "
            "Once the workflow runs in GitHub Actions, the homepage will refresh automatically."
        )

    status_note = f"Using {source_label} data" if articles else "; ".join(notes) if notes else "Live mode ready"
    return {
        "lead": lead,
        "highlights": highlights,
        "watchlist": [
            "Major model launches and benchmark jumps",
            "Enterprise copilots, partnerships, and funding news",
            "Regulatory or safety announcements from major labs",
        ],
        "stats": [
            {"label": "Stories reviewed", "value": str(len(articles))},
            {"label": "Source", "value": source_label},
            {"label": "Status", "value": status_note[:48]},
        ],
    }


def clean_text(value: str, limit: int = 180) -> str:
    cleaned = unescape(value or "")
    cleaned = re.sub(r"(?is)<a\b[^>]*>", " ", cleaned)
    cleaned = re.sub(r"(?is)</a>", " ", cleaned)
    cleaned = re.sub(r"(?i)href\s*=\s*[\"']?[^\"'>\s]+", " ", cleaned)
    cleaned = re.sub(r"(?is)<[^>]+>", " ", cleaned)
    cleaned = re.sub(r"https?://\S+|www\.\S+", " ", cleaned)
    cleaned = re.sub(r"[<>\"']", " ", cleaned)
    compact = re.sub(r"\s+", " ", cleaned).strip(" -–|:\t\n\r")
    if not compact:
        compact = "Open the story for full details."
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1].rstrip() + "…"


def render_html(
    summary: dict[str, Any],
    articles: list[dict[str, str]],
    source_label: str,
    notes: list[str],
) -> str:
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    stat_cards = "".join(
        f"<div class='stat'><span>{escape(str(item['label']))}</span><strong>{escape(str(item['value']))}</strong></div>"
        for item in summary.get("stats", [])
    )

    highlights = "".join(
        f"<li>{escape(str(item))}</li>" for item in summary.get("highlights", [])
    )
    watchlist = "".join(
        f"<li>{escape(str(item))}</li>" for item in summary.get("watchlist", [])
    )

    if articles:
        article_cards = "".join(
            (
                "<article class='card'>"
                f"<h3><a href='{escape(article['url'], quote=True)}' target='_blank' rel='noreferrer'>{escape(article['title'])}</a></h3>"
                f"<p>{escape(clean_text(article['summary'] or article['source']))}</p>"
                f"<div class='card-actions'><a href='{escape(article['url'], quote=True)}' target='_blank' rel='noreferrer'>Read full article ↗</a></div>"
                f"<div class='meta'><span>{escape(article['source'])}</span><span>{escape(clean_text(article['published'], 32) or 'Recent')}</span></div>"
                "</article>"
            )
            for article in articles
        )
    else:
        article_cards = (
            "<article class='card'><h3>No live stories yet</h3>"
            "<p>Enable the GitHub Actions secrets, then run the workflow once to populate this page.</p>"
            "<div class='meta'><span>Setup pending</span><span>Ready</span></div></article>"
        )

    note_text = escape(" | ".join(notes) if notes else f"Using {source_label} data")
    lead = escape(str(summary.get("lead", "Daily AI update ready.")))

    return f"""<!DOCTYPE html>
<html lang='en'>
<head>
  <meta charset='UTF-8' />
  <meta name='viewport' content='width=device-width, initial-scale=1.0' />
  <title>Latest AI News</title>
  <style>
    :root {{
      --bg: #08101f;
      --panel: #101a31;
      --panel-2: #142241;
      --text: #edf2ff;
      --muted: #9fb0d0;
      --accent: #7c9cff;
      --accent-2: #5eead4;
      --border: rgba(159, 176, 208, 0.18);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: Arial, Helvetica, sans-serif;
      background: linear-gradient(180deg, #050b16, var(--bg));
      color: var(--text);
    }}
    .wrap {{ max-width: 1100px; margin: 0 auto; padding: 32px 20px 56px; }}
    .hero {{
      background: linear-gradient(135deg, rgba(124,156,255,.20), rgba(94,234,212,.12));
      border: 1px solid var(--border);
      border-radius: 18px;
      padding: 28px;
      box-shadow: 0 10px 30px rgba(0,0,0,.22);
    }}
    .eyebrow {{ color: var(--accent-2); text-transform: uppercase; font-size: 12px; letter-spacing: 0.18em; }}
    h1 {{ margin: 10px 0 12px; font-size: clamp(30px, 5vw, 46px); }}
    .lead {{ color: var(--muted); line-height: 1.6; max-width: 760px; }}
    .stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; margin-top: 20px; }}
    .stat {{ background: rgba(16,26,49,.82); border: 1px solid var(--border); border-radius: 14px; padding: 14px; }}
    .stat span {{ display: block; color: var(--muted); font-size: 12px; margin-bottom: 6px; }}
    .stat strong {{ font-size: 18px; }}
    .grid {{ display: grid; grid-template-columns: 1.1fr .9fr; gap: 18px; margin-top: 18px; }}
    .panel {{ background: var(--panel); border: 1px solid var(--border); border-radius: 16px; padding: 20px; }}
    .panel h2 {{ margin-top: 0; font-size: 20px; }}
    ul {{ margin: 0; padding-left: 20px; line-height: 1.6; }}
    .cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 14px; margin-top: 18px; }}
    .card {{ background: var(--panel-2); border: 1px solid var(--border); border-radius: 16px; padding: 16px; }}
    .card h3 {{ margin: 0 0 10px; font-size: 17px; }}
    .card a {{ color: var(--text); text-decoration: none; }}
    .card a:hover {{ color: var(--accent-2); }}
    .card p {{ color: var(--muted); line-height: 1.55; }}
    .card-actions {{ margin: 12px 0 10px; }}
    .card-actions a {{
      display: inline-block;
      background: rgba(124,156,255,.18);
      border: 1px solid var(--border);
      border-radius: 999px;
      padding: 8px 12px;
      color: var(--accent-2);
      font-size: 14px;
      font-weight: 700;
    }}
    .card-actions a:hover {{ background: rgba(124,156,255,.28); color: #ffffff; }}
    .meta {{ display: flex; justify-content: space-between; gap: 10px; color: var(--muted); font-size: 12px; border-top: 1px solid var(--border); padding-top: 10px; }}
    footer {{ color: var(--muted); margin-top: 22px; font-size: 13px; }}
    .timestamp {{ position: fixed; top: 20px; right: 20px; background: var(--accent-2); color: var(--bg); border-radius: 8px; padding: 10px 16px; font-size: 13px; font-weight: 600; z-index: 1000; box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3); }}
    @media (max-width: 800px) {{ .grid {{ grid-template-columns: 1fr; }} .timestamp {{ top: 16px; right: 16px; padding: 8px 12px; font-size: 11px; }} }}
  </style>
</head>
<body>
  <div class='timestamp'>Refreshed: {generated_at}</div>
  <main class='wrap'>
    <section class='hero'>
      <div class='eyebrow'>Automated daily briefing</div>
      <h1>Latest AI News</h1>
      <p class='lead'>{lead}</p>
      <div class='stats'>{stat_cards}</div>
    </section>

    <section class='grid'>
      <div class='panel'>
        <h2>Top Highlights</h2>
        <ul>{highlights}</ul>
      </div>
      <div class='panel'>
        <h2>What to Watch</h2>
        <ul>{watchlist}</ul>
      </div>
    </section>

    <section class='cards'>
      {article_cards}
    </section>

    <footer>
      <div>Generated: {generated_at}</div>
      <div>Pipeline: GitHub Actions → Python → Gemini/Tavily → GitHub Pages</div>
      <div>Status: {note_text}</div>
    </footer>
  </main>
</body>
</html>
"""


def main() -> None:
    articles, source_label, notes = collect_articles()
    summary = summarize_with_gemini(articles) or build_fallback_summary(articles, source_label, notes)
    html = render_html(summary, articles, source_label, notes)
    OUTPUT_FILE.write_text(html, encoding="utf-8")
    print(f"Wrote {OUTPUT_FILE.resolve()} with {len(articles)} articles from {source_label}.")


if __name__ == "__main__":
    main()
