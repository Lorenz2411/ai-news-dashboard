# AI News Dashboard

A self-updating dashboard for keeping up with AI news. A GitHub Action pulls headlines from
AI labs, tech press and community feeds every two hours. GitHub Pages serves them as a
searchable, filterable page.

**Features**

- One timeline of the newest stories from labs (OpenAI, Google DeepMind, Hugging Face…),
  tech press (The Verge, TechCrunch, MIT Technology Review…) and community sources (Hacker News, Simon Willison)
- Stories auto-tagged by topic: Models, Research, Tools, Policy, Business, Hardware
- Full-text search (press `/`), time range (24h / 7d / 30d), source and topic filters
- "New since last visit" counter and badges
- ★ Save stories for later (stored in your browser)
- Source health panel showing which feeds are working
- Light / dark theme, works on phones
- No build step, no API keys, no dependencies: one HTML file plus a Python standard-library script

## How it works

```
feeds.json ──► scripts/fetch_news.py ──► docs/data/news.json ──► docs/index.html
                  (GitHub Action, every 2h)                        (GitHub Pages)
```

The fetcher merges new items into the existing `news.json`, so history builds up over time
(items older than `max_age_days` are dropped). A broken feed is reported in the dashboard
but doesn't fail the run.

## Setup

1. **Enable Pages:** *Settings → Pages → Build and deployment → Deploy from a branch →* `main` / `/docs`.
2. **Allow the workflow to push:** *Settings → Actions → General → Workflow permissions →* "Read and write permissions".
3. **Fetch the first batch:** *Actions → Update news → Run workflow*. After that it runs on its own every two hours.

Your dashboard will be at `https://<your-username>.github.io/ai-news-dashboard/`.

> GitHub Pages on the free plan requires a public repository.

## Run locally

```bash
python3 scripts/fetch_news.py          # fetch feeds into docs/data/news.json
python3 -m http.server -d docs 8000    # open http://localhost:8000
python3 -m unittest discover -s tests  # run tests
```

## Customize

- **Add or remove sources:** edit `feeds.json`. Any RSS 2.0, RSS 1.0 or Atom feed works.
  `kind` (`lab`, `press` or `community`) sets the colour dot.
- **Change topics:** edit the `TOPICS` keyword map in `scripts/fetch_news.py`.
- **Change the schedule:** edit the `cron` line in `.github/workflows/update-news.yml`.
