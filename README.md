# jobwatch-AI-python

Uses Claude with web search to look for job postings in a category too fuzzy for keyword matching, and emails me when something new shows up. The current search is QA/testing roles at connected-TV, smart-TV and set-top-box companies.

Split off from `companyjobwatch`; the keyword-scraping half lives in `jobwatch-webscrape-python`.

### How it works
Once a day (GitHub Actions cron, 01:00 UTC), `job_search_ai.py`:

1. Asks Claude (with the server-side web search tool) for current matching postings, returned as a JSON list of `{company, title, location, url}`
2. Compares them against `history.json`, the record of postings already seen
3. Emails any new postings, then commits the updated `history.json` back to the repo

Postings that drop out of the results are removed from history, so if one shows up again later it gets reported again. Search results vary from run to run, so expect some postings to drop out and come back.

### Layout
```
jobwatch-AI-python/
├── .github/workflows/jobwatch.yml   # Daily schedule + manual trigger; commits history.json
├── job_search_ai.py                 # Search prompt, Claude call, diffing, and emailing
├── history.json                     # Postings already seen (don't hand-edit)
└── requirements.txt
```

### Usage

**Run locally:**
1. `pip install -r requirements.txt`
2. Set `ANTHROPIC_API_KEY`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `EMAIL_FROM` and `EMAIL_TO`
3. `python job_search_ai.py`

Each run makes a paid API call with up to 10 web searches. A local run also updates `history.json`, so the next scheduled run won't report anything this run already found.

**Run via GitHub Actions:**
1. Add the seven values above as repository secrets
2. It runs daily on its own; to trigger it by hand, go to the **Actions** tab → **Job Watch (AI)** → **Run workflow**

### Changing the search
Edit `PROMPT` in `job_search_ai.py`. If the search changes enough that old results no longer apply, also change `SEARCH_KEY` so it starts a fresh history.
