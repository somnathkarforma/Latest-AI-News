# Latest AI News

A free, serverless AI-news tracker that refreshes itself every day using **GitHub Actions**, summarizes recent stories with **Gemini**, and serves a static website with **GitHub Pages**.

## What this repo does

1. Runs on a daily GitHub Actions schedule.
2. Pulls recent AI news from **Tavily** when configured, with a **Google News RSS** fallback.
3. Uses **Gemini** to create a concise briefing.
4. Rewrites `index.html` so the site stays up to date.

## Quick setup

### 1) Add repository secrets
In GitHub, open **Settings → Secrets and variables → Actions** and add:

- `GEMINI_API_KEY` — required for AI summaries
- `TAVILY_API_KEY` — optional but recommended for better search quality

### 2) Enable GitHub Pages
Open **Settings → Pages** and set:

- **Source:** `Deploy from a branch`
- **Branch:** `main`
- **Folder:** `/ (root)`

After that, your site will be available at:

```text
https://<your-username>.github.io/Latest-AI-News/
```

## Local run

```bash
py -m pip install -r requirements.txt
py app.py
```

This generates or refreshes `index.html`.

## Schedule note

The workflow uses this cron entry:

```yaml
- cron: '0 22 * * *'
```

That is **5:00 PM EST** in UTC-based GitHub Actions scheduling.

## Files

- `app.py` — fetches news, summarizes, and generates the static page
- `.github/workflows/daily.yml` — automation schedule
- `index.html` — the published site
