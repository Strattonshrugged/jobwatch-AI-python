# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

`jobwatch-AI-python` does an AI-driven web search (Claude + the web-search tool) for a job category too fuzzy for keyword matching, keeps a history of postings already seen, and emails a summary whenever new ones appear. It runs on a GitHub Actions cron schedule.

It was split off from `companyjobwatch` (Oct 2026), which ran this script next to a keyword scraper. The scraper now lives on its own in `jobwatch-webscrape-python`. This repo keeps companyjobwatch's git history, but `history.json` was reset to `{}`: companyjobwatch's history file never held an entry for the AI search, only the scraper's per-site matches.

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run the search locally (requires env vars below; makes a real, billed API call)
python job_search_ai.py
```

Required environment variables:
```
ANTHROPIC_API_KEY, SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, EMAIL_FROM, EMAIL_TO
```

## Architecture

All logic lives in `job_search_ai.py`:

1. Loads `history.json` (postings already seen, keyed by search)
2. Calls the Claude API with the `web_search_20260209` server-side tool (model `claude-opus-5`, `output_config.effort: "medium"`, deliberately below the `high` default to keep a routine daily job cheap; raise it if results seem thin), asking for QA/testing postings in the connected-devices / smart-TV / set-top-box space as a JSON array of `{company, title, location, url}`. If the response stops with `pause_turn`, the request is resent (up to 5 times) so the server-side tool loop can continue.
3. Diffs the results against history under `SEARCH_KEY = "ai-search:connected-devices-smart-tv-stb"`. New postings go into the email; postings missing from this run are removed from history.
4. Saves updated `history.json`
5. If anything is new, sends a single SMTP email listing it

History is a dict keyed by search rather than a flat list, so another search can be added later with its own key without mixing results.

If the API call fails or the response doesn't parse as JSON (`extract_json_array` raises), the script logs to stderr and exits 1 without touching `history.json`. The workflow run goes red and the commit step is skipped. When the script still ran next to the scraper in companyjobwatch, it returned 0 here instead, so a failure couldn't block the scraper's run. Now that it runs alone, a silent pass would hide the failure. If parsing keeps failing, check the Actions log for the raw response text and tighten the prompt (e.g. the model wrapping the array in markdown fences or commentary).

**Not yet verified against the live API.** It was built and dry-run with a stub and no key (2026-09-10) in companyjobwatch, but nobody has seen it complete a real `web_search` call end to end. The first real check will be a local run with `ANTHROPIC_API_KEY` set, or the first `workflow_dispatch`/scheduled run once the secret is added, whichever comes first.

**`history.json`** is committed back to the repo by the Actions workflow after each run; don't edit it by hand. Changing `SEARCH_KEY` starts a fresh history for that search, which means one burst of "new" postings on the next run.
**`.github/workflows/jobwatch.yml`**: the cron schedule is `0 1 * * *` (01:00 UTC = 6:00 PM Pacific Daylight Time daily). GitHub Actions cron is fixed UTC and doesn't follow DST, so it drifts to 5:00 PM Pacific during Standard Time (roughly Nov–Mar). Uses `workflow_dispatch` for manual triggers.

## Known limitations

- Results aren't deterministic: the same posting can drop out of one run and come back in the next, which gets reported as "new" again. If that churn gets noisy, a fix is to stop removing postings that are missing from just one run (e.g. only drop them after N consecutive misses).
- The model is told to include only postings with a real URL, but nothing checks the URLs. Hallucinated or stale links are possible.

## GitHub Secrets Required

| Secret | Description |
|---|---|
| `ANTHROPIC_API_KEY` | Claude API key |
| `SMTP_HOST` | SMTP server hostname |
| `SMTP_PORT` | SMTP port (typically `587`) |
| `SMTP_USER` | SMTP login username |
| `SMTP_PASSWORD` | SMTP password or app password |
| `EMAIL_FROM` | Sender address |
| `EMAIL_TO` | Recipient address |
