import json
import os
import re
import smtplib
import sys
from collections import Counter
from datetime import date, timedelta
from email.mime.text import MIMEText

import anthropic

HISTORY_FILE = "history.json"

# Not a URL - just a stable key for this search's entry in history.json, so
# more searches can be added later without sharing one list.
SEARCH_KEY = "ai-search:connected-devices-smart-tv-stb"

# Web search results vary run to run, so a posting missing from one run isn't
# necessarily gone. Keep it in history until it's been unseen this long, so a
# posting that drops out and comes back isn't emailed again as "new".
FORGET_AFTER_DAYS = 60

PROMPT = """Search the web for current QA, software testing, and quality assurance job \
openings at companies that build connected TV apps, smart TV platforms, or set-top box / \
streaming device software. This includes companies making the devices and firmware (e.g. \
Roku, Amazon Fire TV, Google TV, Samsung Tizen, LG webOS, Comcast/Xfinity, set-top box \
vendors) as well as companies building apps FOR those platforms (streaming services, \
connected-device software vendors, smart TV ad/analytics platforms).

Focus specifically on QA Engineer, QA Analyst, Software Test Engineer, SDET, Quality \
Assurance, UAT, or similar testing-focused roles - not general software engineering roles, \
even at these companies.

Search broadly (job boards, company career pages, LinkedIn postings) rather than relying on \
memory - only include postings you can point to a real URL for.

For each posting, also record anything that identifies that specific posting, so it can be \
told apart from an identical-looking repost of the same role:
- "requisition_id": the requisition / job ID / reference number shown on the posting or in \
its URL (e.g. "R-12345", "JR104233", a Greenhouse or Workable job ID)
- "posted_date": the date the posting was originally published, as YYYY-MM-DD
Only report values you actually saw on the posting or in its URL - use null rather than \
guessing. Prefer the company's own career page URL over a job board copy when both exist.

Respond with ONLY a JSON array (no other text before or after it) of objects with these \
exact keys: "company", "title", "location", "url", "requisition_id", "posted_date". If you \
find no relevant postings, respond with an empty array: []"""


def load_history():
    try:
        with open(HISTORY_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_history(history):
    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=2)
        f.write("\n")


LEGAL_SUFFIXES = {"inc", "llc", "ltd", "corp", "corporation", "co", "company", "plc", "gmbh"}


def _norm(value):
    return " ".join(re.sub(r"[^a-z0-9]+", " ", str(value).lower()).split())


def _norm_company(name):
    # "Multi Media LLC" and "Multi Media, LLC." should be the same company.
    return " ".join(w for w in _norm(name).split() if w not in LEGAL_SUFFIXES)


def posting_keys(job, use_url):
    """Identities a posting can be matched against history on, most specific first.

    A requisition ID is authoritative on its own: two postings with identical
    title/text but different requisition numbers are different postings. Without
    one, the original posting date (so a copy-pasted repost of the same role on a
    later date counts as new) and the posting's URL are both used, and matching
    either one counts as already seen.
    """
    company = _norm_company(job.get("company", ""))
    if job.get("requisition_id"):
        return [f"req:{company}:{_norm(job['requisition_id'])}"]

    keys = []
    if job.get("posted_date"):
        keys.append(
            f"dated:{company}:{_norm(job.get('title', ''))}:"
            f"{_norm(job.get('location') or '')}:{_norm(job['posted_date'])}"
        )
    if use_url and job.get("url"):
        keys.append(f"url:{job['url'].split('#')[0].rstrip('/').lower()}")
    if not keys:
        keys.append(
            f"listing:{company}:{_norm(job.get('title', ''))}:{_norm(job.get('location') or '')}"
        )
    return keys


def describe(posting):
    line = f"{posting['company']} - {posting['title']} ({posting['location']}) - {posting['url']}"
    if posting.get("requisition_id"):
        line += f" [Req {posting['requisition_id']}]"
    if posting.get("posted_date"):
        line += f" [Posted {posting['posted_date']}]"
    return line


def send_email(new_lines):
    host = os.environ["SMTP_HOST"]
    port = int(os.environ["SMTP_PORT"])
    user = os.environ["SMTP_USER"]
    password = os.environ["SMTP_PASSWORD"]
    email_from = os.environ["EMAIL_FROM"]
    email_to = os.environ["EMAIL_TO"]

    lines = ["New postings found:\n", "Connected Devices / Smart TV / STB QA Search (AI)"]
    for line in new_lines:
        lines.append(f"  - {line}")

    body = "\n".join(lines).strip()
    subject = f"[jobwatch-AI-python] New postings found — {date.today()}"

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = email_from
    msg["To"] = email_to

    with smtplib.SMTP(host, port) as smtp:
        smtp.starttls()
        smtp.login(user, password)
        smtp.sendmail(email_from, [email_to], msg.as_string())

    print(f"Email sent to {email_to}")


def extract_json_array(text):
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if not match:
        raise ValueError(f"No JSON array found in response: {text[:500]}")
    return json.loads(match.group(0))


def search_jobs(client):
    messages = [{"role": "user", "content": PROMPT}]
    response = None
    for _ in range(5):
        response = client.messages.create(
            model="claude-opus-5-5",
            max_tokens=8000,
            output_config={"effort": "medium"},
            tools=[{"type": "web_search_20260209", "name": "web_search", "max_uses": 10}],
            messages=messages,
        )
        if response.stop_reason != "pause_turn":
            break
        # Server-tool loop hit its iteration cap - resend to let it continue.
        messages = [messages[0], {"role": "assistant", "content": response.content}]

    text = next(
        (b.text for b in reversed(response.content) if b.type == "text"), ""
    )
    return extract_json_array(text)


def main():
    history = load_history()
    client = anthropic.Anthropic()

    try:
        jobs = search_jobs(client)
    except Exception as e:
        # Leave history.json untouched, but fail the run so it shows up red in Actions.
        print(f"ERROR searching for jobs: {e}", file=sys.stderr)
        sys.exit(1)

    jobs = [job for job in jobs if job.get("company") and job.get("title") and job.get("url")]
    today = date.today().isoformat()
    entries = history.get(SEARCH_KEY, {})
    index = {key: entry_id for entry_id, entry in entries.items() for key in entry["match_keys"]}
    # A URL the model gave for more than one posting this run is a generic
    # careers page, not a posting - matching on it would hide new postings.
    url_counts = Counter(job["url"] for job in jobs)

    new_postings = []
    for job in jobs:
        keys = posting_keys(job, use_url=url_counts[job["url"]] == 1)
        entry_id = next((index[key] for key in keys if key in index), None)
        if entry_id is None:
            entry_id = keys[0]
            entries[entry_id] = {
                "company": job["company"],
                "title": job["title"],
                "location": job.get("location") or "",
                "url": job["url"],
                "requisition_id": job.get("requisition_id"),
                "posted_date": job.get("posted_date"),
                "first_seen": today,
                "match_keys": keys,
            }
            index.update({key: entry_id for key in keys})
            new_postings.append(entries[entry_id])
        entries[entry_id]["last_seen"] = today

    cutoff = (date.today() - timedelta(days=FORGET_AFTER_DAYS)).isoformat()
    forgotten = [entry_id for entry_id, entry in entries.items() if entry["last_seen"] < cutoff]
    for entry_id in forgotten:
        del entries[entry_id]

    if new_postings:
        print(f"{len(new_postings)} new posting(s) found")
    if forgotten:
        print(f"{len(forgotten)} posting(s) unseen for {FORGET_AFTER_DAYS}+ days, removed from history")

    history[SEARCH_KEY] = dict(sorted(entries.items()))
    save_history(history)
    print("History saved.")

    if new_postings:
        send_email(sorted(describe(posting) for posting in new_postings))
    else:
        print("No new matches - no email sent.")


if __name__ == "__main__":
    main()
