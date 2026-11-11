# GitHub Enterprise Scan

A small Python tool (no HTML, no web page) that scans public GitHub repos for new and rising projects, twice a week, on three topics:

1. **Enterprise AI** – usage-based API, enterprise commitments, seats, on-prem licences, paid forward-deployed engineering.
2. **GTMSO / GTM Strategy & Ops** – how AI companies plan, price, forecast, and run the revenue motion.
3. **Southeast Asia build-out** – who is building for Singapore and the region.

It is the scanner behind the twice-weekly GitHub scan (Tue/Fri). Each run writes a short Markdown report, not a huge dump.

## What you get

- `scan.py` – the whole tool, one file, Python standard library only.
- `reports/YYYY-MM-DD.md` – one short report per run. Each repo has a name and link, stars, star velocity (stars per day), created date, a one-line description from GitHub, and a "Why it matters for GTM/DevEx" line.
- `.seen.json` – repos already reported in an earlier run, so the next report can flag what is genuinely new to this scan. It is created automatically; you do not need to edit it.

## How to run it

```bash
python3 scan.py
```

That looks back 14 days and writes `reports/<today>.md`.

```bash
python3 scan.py --days 7            # look back 7 days instead of 14
python3 scan.py --max-per-topic 3    # fewer repos per topic
```

No install step: Python 3.10+ standard library only, no `pip install` needed. See `requirements.txt`.

### Rate limits (worth knowing)

GitHub's public search allows 10 searches per minute without a login, 30 per minute with a free personal token. This script waits between calls, so it stays inside the limit. If it ever hits the limit, it waits once and retries; if that fails, it stops and writes **no** report, rather than writing a partial one that looks complete.

To use a token (optional, faster):

```bash
GITHUB_TOKEN=ghp_your_token_here python3 scan.py
```

Never put a token in `scan.py` or commit one to GitHub.

## How it ranks repos

- **New** = created in the look-back window, ranked by star velocity: stars divided by days since creation. A repo with 100 stars in 10 days outranks one with 1,000 stars in 3 years.
- **Rising** = an older repo updated in the window, with a minimum star count. This catches established projects that are active again.
- Forks (copies of someone else's repo) are skipped.

## How to add a topic

Open `scan.py` and copy one block in the `TOPICS` list at the top. Each topic needs:

- `name` – the heading in the report.
- `why` – one or two sentences on why the topic matters.
- `queries` – search phrases. Use `{"kind": "new", "q": "..."}` for brand-new repos, and `{"kind": "rising", "q": "...", "min_stars": 20}` for older, active ones.

Example:

```python
{
    "name": "AI evals",
    "why": "Evals decide whether an enterprise PoC survives contact with real users.",
    "queries": [
        {"kind": "new", "q": "LLM evals"},
        {"kind": "rising", "q": "LLM evaluation", "min_stars": 20},
    ],
},
```

## What I learned

Format: challenge, what was misunderstood at first, what was learned, what to fix/check.

### 1. Stars alone are not "rising" (real, from building this)

- **Challenge:** find rising repos, not just popular ones.
- **What was misunderstood at first:** that searching for repos "updated in the last 14 days, sorted by stars" would surface rising projects.
- **What was learned:** it surfaces giants. A test search returned LangChain (149,328 stars) and LangGraph (44,769 stars) – established projects that happen to be active, not rising ones. Stars alone measure size, not speed.
- **What to fix/check:** split the scan in two. "New" repos are ranked by star velocity (stars per day since creation). "Rising" repos are kept separate, capped at 2 per topic, and only from narrow topical queries (for example "forward deployed"), so a giant repo cannot flood the report.

### 2. Niche topics return almost nothing in 14 days (real, from building this)

- **Challenge:** GTMSO and Southeast Asia are the topics Irving cares about, but they are quiet on GitHub.
- **What was misunderstood at first:** that every topic would return a healthy list of new repos each run.
- **What was learned:** in a test run, "go-to-market operations" returned only 2 new repos in 14 days, and "Southeast Asia" only 24, most with 0–1 stars. An empty section is a real result for a niche topic, not a bug.
- **What to fix/check:** keep the "Rising" bucket for these topics, and if a topic stays empty for several runs, widen its queries or lengthen the window with `--days 30` before deciding the topic is wrong.

### 3. [Add your own here]

- **Challenge:**
- **What was misunderstood at first:**
- **What was learned:**
- **What to fix/check:**
