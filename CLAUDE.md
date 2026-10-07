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
2. Calls the Claude API with the `web_search_20260209` server-side tool (model `claude-opus-5-5`, `output_config.effort: "medium"`, set explicitly to keep a routine daily job cheap even though it's this model's default; raise it to `high` if results seem thin), asking for QA/testing postings in the connected-devices / smart-TV / set-top-box space as a JSON array of `{company, title, location, url, requisition_id, posted_date}`. The last two are `null` unless the model actually saw them on the posting or in its URL. If the response stops with `pause_turn`, the request is resent (up to 5 times) so the server-side tool loop can continue.
3. Matches each result against history under `SEARCH_KEY = "ai-search:connected-devices-smart-tv-stb"` (see "Posting identity" below). Unmatched postings are added and go into the email; matched ones get their `last_seen` bumped.
4. Drops postings not seen for `FORGET_AFTER_DAYS` (60) and saves `history.json`
5. If anything is new, sends a single SMTP email listing it, with requisition ID and posted date when known

History is a dict keyed by search, so another search can be added later with its own key without mixing results. Each search's value is a dict of postings keyed by their primary identity key. Each posting stores its details, `first_seen`/`last_seen`, and the `match_keys` it can be matched on.

### Posting identity

Python decides whether a posting is new, not the model, and the history is never sent to the API. Claude's only job here is to read the requisition ID and posted date off the posting; the comparison is a plain key lookup, so it's deterministic and adds no tokens. `posting_keys()` builds the keys:

- **Requisition ID present:** `req:<company>:<req id>` is the only key. It's authoritative because companies (e.g. Multi Media LLC) post copy-pasted, identical-looking listings for the same role under different requisition numbers, and those are separate postings. The same requisition found via a different URL or job board is the same posting.
- **No requisition ID:** match on either `dated:<company>:<title>:<location>:<posted date>` (when a date is known, so a repost of the same role on a later date counts as new) or the posting URL, with a final `listing:<company>:<title>:<location>` fallback when neither is available.

Company names are normalized (case, punctuation, legal suffixes like LLC/Inc), so "Multi Media, LLC." and "Multi Media LLC" match. A URL that more than one posting shares in the same run is treated as a generic careers page and not used as a key, since matching on it would hide new postings. The keys are stored per entry (`match_keys`) rather than recomputed from the stored fields, so that URL exclusion still holds on later runs.

When unsure, this errs toward emailing: a posting seen once with a requisition ID and once without one won't match, and comes through as a duplicate rather than a missed new posting.

Postings missing from a single run stay in history (web search results vary from run to run), so one that drops out and comes back isn't re-reported. They're removed only after `FORGET_AFTER_DAYS` unseen.

If the API call fails or the response doesn't parse as JSON (`extract_json_array` raises), the script logs to stderr and exits 1 without touching `history.json`. The workflow run goes red and the commit step is skipped. When the script still ran next to the scraper in companyjobwatch, it returned 0 here instead, so a failure couldn't block the scraper's run. Now that it runs alone, a silent pass would hide the failure. If parsing keeps failing, check the Actions log for the raw response text and tighten the prompt (e.g. the model wrapping the array in markdown fences or commentary).

**Not yet verified against the live API.** It was built and dry-run with a stub and no key (2026-09-10) in companyjobwatch, but nobody has seen it complete a real `web_search` call end to end. The first real check will be a local run with `ANTHROPIC_API_KEY` set, or the first `workflow_dispatch`/scheduled run once the secret is added, whichever comes first.

**`history.json`** is committed back to the repo by the Actions workflow after each run; don't edit it by hand. Changing `SEARCH_KEY` starts a fresh history for that search, which means one burst of "new" postings on the next run.
**`.github/workflows/jobwatch.yml`**: the cron schedule is `0 1 * * *` (01:00 UTC = 6:00 PM Pacific Daylight Time daily). GitHub Actions cron is fixed UTC and doesn't follow DST, so it drifts to 5:00 PM Pacific during Standard Time (roughly Nov–Mar). Uses `workflow_dispatch` for manual triggers.

## Known limitations

- Requisition IDs and posted dates are only as good as what the model reads off the page. A misread ID makes a known posting look new (a duplicate email). A misread date has the same effect when there's no requisition ID.
- A posting with no requisition ID or date whose URL is only a generic careers page can still claim that URL as its identity if it's the only result at that URL in its run. A later different posting at the same generic URL would then be matched to it and not reported.
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
