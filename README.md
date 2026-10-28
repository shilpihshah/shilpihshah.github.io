# Shilpi Shah: Notes on AI & Venture

A static personal site with four tabs: **Blog**, a live **VC Pulse** dashboard of AI funding rounds, **Key voices**, and **About**.
There's no build step and no runtime dependencies. The data updater uses only the Python standard library.

## Files
| Path | What it is |
|---|---|
| `index.html` | Blog, Dashboard, Key voices, and About (hash tabs: `#blog`, `#dashboard`, `#voices`, `#about`) |
| `posts/*.html` | Blog posts |
| `assets/style.css`, `assets/dashboard.js` | Styles; tab routing, dashboard rendering, and Key voices (inline SVG charts, no CDN) |
| `data/key_voices.json` | Summaries for the Key voices tab. The daily updater does not write this file. |
| `update_data.py` | Pulls public RSS feeds, extracts AI funding rounds, and writes `data.json` |
| `data.json` | Generated data: rounds, news, per-source status, `generated_at` |
| `pitchbook_snapshot.json` | Optional manual PitchBook snapshot. While `deals` is empty, the dashboard shows "Coming soon" |
| `.github/workflows/update.yml` | Daily GitHub Action that re-runs the updater and commits `data.json` |
| `index-v1.html` | Backup of the previous explainer-style page |
| `DRAFT_NOTES.md` | Private editing notes for the draft posts |

## Run locally
```bash
python3 update_data.py          # refresh data.json (~5 s)
python3 -m http.server 8000     # then open http://localhost:8000/#dashboard
```
The dashboard loads `data.json` with `fetch`, so it needs to be served over http. Opening the file directly (`file://`) won't load the data.

## Host on GitHub Pages (about 5 minutes)
1. Create a public repo, e.g. `shilpi-notes`, and push this folder's contents to the repo root:
   ```bash
   git init && git add . && git commit -m "Initial site"
   git branch -M main
   git remote add origin https://github.com/<you>/shilpi-notes.git
   git push -u origin main
   ```
2. Go to **Settings → Pages → Build and deployment**, set Source to "Deploy from a branch", Branch to `main`, and folder to `/ (root)`. Save.
3. Go to **Settings → Actions → General → Workflow permissions** and select **Read and write permissions** so the workflow can commit `data.json`.
4. Go to **Actions → "Update VC Pulse data" → Run workflow** once to test it. After that it runs every day at 11:17 UTC, and each commit redeploys Pages.
5. The site will be live at `https://<you>.github.io/shilpi-notes/`. Custom domain is optional (Settings → Pages).

## How the data works
- **Sources:** TechCrunch (Venture, AI), Crunchbase News, VentureBeat AI (with a Feedburner fallback), SiliconANGLE AI, and four Google News RSS queries (AI Series A, Series B, seed, Series C+).
- **Extraction:** rule-based regex on headlines and summaries pulls out company, round type, amount (USD millions; EUR/GBP converted approximately and shown with ≈), lead investors when the text says "led by / from / backed by", and one or two sector tags from keyword rules.
- **Dedupe:** the same company within 7 days counts as one round. The richer record is kept, and other outlets are listed in `also_reported_by`.
- **History:** each run merges with the previous `data.json` and keeps a rolling 45-day window, so history builds up over time.
- **Failures:** if a feed fails (VentureBeat sometimes returns HTTP 429 to datacenter IPs), the run continues and the failure shows in the dashboard's Sources card.
- **PitchBook:** no public API, so add rows to `pitchbook_snapshot.json` by hand from an export (fields are in `_example_deal`).

Headline parsing is heuristic. Company names, stages, or investors will sometimes be missed or misread, so check the linked source before relying on a figure.
