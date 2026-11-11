#!/usr/bin/env python3
"""
github-enterprise-scan: a small Python tool, not a web page.

What it does, in plain words:
  - Asks GitHub's public search (no login needed) for repos that are
    new or recently active, on three topics Irving cares about:
      1. Enterprise AI
      2. GTMSO / GTM Strategy & Ops
      3. Southeast Asia build-out
  - Ranks them by "star velocity": stars divided by days since the
    repo was created. A repo with 100 stars in 10 days is rising
    faster than a repo with 1,000 stars in 3 years.
  - Writes a short Markdown report to reports/YYYY-MM-DD.md.
    Only the most interesting few repos per topic, never a huge dump.

How to run it:
  python3 scan.py

  Optional extras:
    python3 scan.py --days 7            # look back 7 days instead of 14
    python3 scan.py --max-per-topic 3    # fewer repos per topic
    GITHUB_TOKEN=ghp_... python3 scan.py  # optional token: raises the
                                          # GitHub limit from 10 searches
                                          # per minute to 30 per minute.
                                          # Never put a token in this file.

Needs nothing to install: Python 3.10+ standard library only.
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone

# ---------------------------------------------------------------------------
# Topics: the only part most people will ever need to edit.
# Each topic has a short "why it matters" base line, plus search queries.
# A query is either:
#   "new"    -> repos CREATED in the look-back window (brand new)
#   "rising" -> older repos PUSHED (updated) in the window, with a
#               minimum star count (already established, active again)
# Add a topic by copying one block below and adding its queries.
# ---------------------------------------------------------------------------
TOPICS = [
    {
        "name": "Enterprise AI",
        "why": "Enterprise AI is the market this scan watches: usage-based API, "
               "enterprise commitments, seats, on-prem licences, and paid "
               "forward-deployed engineering.",
        "queries": [
            {"kind": "new", "q": "enterprise AI agents"},
            {"kind": "new", "q": "LLM enterprise"},
            {"kind": "rising", "q": "forward deployed", "min_stars": 10},
        ],
    },
    {
        "name": "GTMSO / GTM Strategy & Ops",
        "why": "GTM Strategy & Ops is the job family: how AI companies plan, "
               "price, forecast, and run the revenue motion, not just the product.",
        "queries": [
            {"kind": "new", "q": "go-to-market operations"},
            {"kind": "new", "q": "GTM strategy"},
            {"kind": "rising", "q": "go-to-market", "min_stars": 20},
        ],
    },
    {
        "name": "Southeast Asia build-out",
        "why": "Southeast Asia build-out is the region angle: who is building "
               "for Singapore and the region, and what developers there are using.",
        "queries": [
            {"kind": "new", "q": "Southeast Asia"},
            {"kind": "new", "q": "Singapore AI"},
            {"kind": "rising", "q": "Southeast Asia", "min_stars": 20},
        ],
    },
]

# Extra "why it matters" clues, matched against a repo's name/description.
# These only add a clause when the words are actually there; they never
# invent a feature the repo does not claim.
KEYWORD_CLUES = [
    ("forward deploy", "Forward-deployed angle: this is the delivery motion that turns a PoC into production."),
    ("fde", "Forward-deployed angle: this is the delivery motion that turns a PoC into production."),
    ("agent", "Agent angle: watch how it is packaged for enterprise use, not just the demo."),
    ("mcp", "MCP angle: an integration surface other developers can build on."),
    ("rag", "RAG angle: retrieval is often where enterprise PoCs succeed or stall."),
    ("on-prem", "On-prem angle: self-hosted deployment, a real enterprise revenue stream."),
    ("self-host", "On-prem angle: self-hosted deployment, a real enterprise revenue stream."),
    ("singapore", "Singapore angle: a local signal, worth a closer look for the region."),
    ("southeast asia", "Southeast Asia angle: a regional signal, not just a US/EU one."),
    ("gtm", "GTM angle: a tool or playbook for the go-to-market motion itself."),
    ("revops", "RevOps angle: touches forecasting, pipeline, or operations tooling."),
    ("forecast", "Forecast angle: relevant to the sales-forecast check in the WBR deck."),
]

API_URL = "https://api.github.com/search/repositories"
# GitHub's unauthenticated search limit is 10 requests per minute.
# With a token it is 30 per minute. We wait between calls either way,
# so the script never hammers the API.
PAUSE_NO_TOKEN = 7   # seconds between search calls without a token
PAUSE_WITH_TOKEN = 2  # seconds between search calls with a token
SEEN_FILE = ".seen.json"  # repos already reported in an earlier run


def parse_args():
    p = argparse.ArgumentParser(description="Scan GitHub for new/rising repos on three topics.")
    p.add_argument("--days", type=int, default=14,
                   help="Look-back window in days (default 14).")
    p.add_argument("--max-per-topic", type=int, default=5,
                   help="Max repos shown per topic (default 5).")
    p.add_argument("--output", default=None,
                   help="Report path. Default: reports/YYYY-MM-DD.md")
    return p.parse_args()


def github_search(query, token, pause):
    """One search call. Returns the parsed JSON, or None on a rate limit.

    On 403/429 GitHub tells us when to retry (Retry-After, or the
    X-RateLimit-Reset clock time). We honour that instead of guessing,
    wait once, and if it still fails we stop cleanly with a message
    rather than writing a report full of made-up data.
    """
    params = {"q": query, "sort": "stars", "order": "desc", "per_page": 8}
    url = API_URL + "?" + urllib.parse.urlencode(params)
    headers = {"Accept": "application/vnd.github+json",
               "User-Agent": "github-enterprise-scan"}
    if token:
        headers["Authorization"] = "Bearer " + token
    for attempt in (1, 2):
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                print(f"  rate limit left: {resp.headers.get('X-RateLimit-Remaining')}")
                return json.load(resp)
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")[:300]
            if e.code in (403, 429):
                wait = None
                if e.headers.get("Retry-After"):
                    wait = int(e.headers["Retry-After"])
                elif e.headers.get("X-RateLimit-Reset"):
                    wait = max(0, int(e.headers["X-RateLimit-Reset"]) - int(time.time()))
                print(f"  GitHub rate limit hit ({e.code}). {body}")
                if wait is not None and attempt == 1 and wait <= 300:
                    print(f"  Waiting {wait}s, then one retry...")
                    time.sleep(wait + 1)
                    continue
                print("  Stopping: rate limit. Try again later, or set GITHUB_TOKEN.")
                return None
            print(f"  GitHub returned {e.code}: {body}")
            return None
        except Exception as e:  # network down, DNS, timeout, ...
            print(f"  Could not reach GitHub: {e}")
            return None
        finally:
            time.sleep(pause)
    return None


def days_since(iso_date):
    """Days between a GitHub '2026-11-01T12:00:00Z' date and today."""
    dt = datetime.fromisoformat(iso_date.replace("Z", "+00:00"))
    return max(1, (datetime.now(timezone.utc) - dt).days)


def star_velocity(repo):
    """Stars per day since creation. This is the ranking signal."""
    return repo["stargazers_count"] / days_since(repo["created_at"])


def why_it_matters(repo, topic):
    """One honest line, built from the topic plus words actually in
    the repo's name/description. No invented features."""
    text = ((repo.get("name") or "") + " " + (repo.get("description") or "")).lower()
    clues = [line for word, line in KEYWORD_CLUES if word in text]
    line = topic["why"]
    if clues:
        line += " " + clues[0]
    return line


def load_seen():
    try:
        with open(SEEN_FILE, encoding="utf-8") as f:
            return set(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError):
        return set()


def save_seen(seen):
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(seen), f, indent=2)


def main():
    args = parse_args()
    token = os.environ.get("GITHUB_TOKEN", "").strip() or None
    pause = PAUSE_WITH_TOKEN if token else PAUSE_NO_TOKEN
    today = date.today()
    since = (today - timedelta(days=args.days)).isoformat()

    print(f"GitHub enterprise scan: {today} (window: last {args.days} days, since {since})")
    print(f"Auth: {'token set (30 searches/min)' if token else 'no token (10 searches/min, slower)'}")

    seen_before = load_seen()
    seen_now = set(seen_before)
    results = {}   # topic name -> {"new": [...], "rising": [...]}
    failed = []

    for topic in TOPICS:
        print(f"\n[{topic['name']}]")
        found = {}  # full_name -> repo dict (dedupe within a topic)
        for spec in topic["queries"]:
            if spec["kind"] == "new":
                q = f"{spec['q']} created:>{since}"
            else:
                q = f"{spec['q']} pushed:>{since} stars:>={spec.get('min_stars', 10)}"
            print(f"  searching: {q}")
            data = github_search(q, token, pause)
            if data is None:
                failed.append(f"{topic['name']}: {spec['q']}")
                continue
            for item in data.get("items", []):
                if item.get("fork"):
                    continue  # forks are copies, not new work
                # "new" means created in the window; "rising" means older
                # but updated in the window.
                created_recent = item["created_at"][:10] >= since
                if spec["kind"] == "new" and not created_recent:
                    continue
                if spec["kind"] == "rising" and created_recent:
                    continue  # it will show up under "new" instead
                item["_bucket"] = spec["kind"]
                item["_topic"] = topic["name"]
                found[item["full_name"]] = item
        new = sorted((r for r in found.values() if r["_bucket"] == "new"),
                     key=star_velocity, reverse=True)[: args.max_per_topic]
        rising = sorted((r for r in found.values() if r["_bucket"] == "rising"),
                        key=lambda r: r["stargazers_count"], reverse=True)[:2]
        results[topic["name"]] = {"new": new, "rising": rising, "topic": topic}
        print(f"  -> {len(new)} new, {len(rising)} rising")

    if failed:
        print("\nSome searches failed (see above). No report written, "
              "so a partial run never looks like a complete one.")
        return 1

    # ---- Write the Markdown report -------------------------------------
    out_path = args.output or os.path.join("reports", f"{today.isoformat()}.md")
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    total = sum(len(v["new"]) + len(v["rising"]) for v in results.values())

    lines = [
        f"# GitHub enterprise scan: {today.isoformat()}",
        "",
        f"Window: last {args.days} days (since {since}). "
        "New = created in the window, ranked by star velocity (stars per day). "
        "Rising = older repo, updated in the window. "
        "Only the most interesting few per topic are listed.",
        "",
    ]
    for topic in TOPICS:
        name = topic["name"]
        bucket = results[name]
        lines.append(f"## {name}")
        lines.append("")
        if not bucket["new"] and not bucket["rising"]:
            lines.append("No new or rising repos in this window. "
                         "That is a real result for a niche topic, not an error.")
            lines.append("")
            continue
        for label, repos in (("New", bucket["new"]), ("Rising", bucket["rising"])):
            if not repos:
                continue
            lines.append(f"### {label}")
            lines.append("")
            for repo in repos:
                flag = "seen before" if repo["full_name"] in seen_before else "new to this scan"
                seen_now.add(repo["full_name"])
                desc = (repo.get("description") or "No description on GitHub.").strip()
                n = repo["stargazers_count"]
                stars = f"{n} star" if n == 1 else f"{n} stars"
                # Star velocity only makes sense for New repos. For Rising
                # (older) repos it would be a lifetime average, not a
                # recent speed, so it is left out there.
                velocity = f", {star_velocity(repo):.1f} stars/day" if label == "New" else ""
                lines.append(f"- **[{repo['full_name']}]({repo['html_url']})** "
                             f"({stars}{velocity}, "
                             f"created {repo['created_at'][:10]}, {flag})")
                lines.append(f"  - {desc}")
                lines.append(f"  - Why it matters for GTM/DevEx: {why_it_matters(repo, topic)}")
            lines.append("")
    lines.append(f"_Total surfaced: {total} repos. Generated by `scan.py` from the live GitHub Search API._")
    lines.append("")

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    save_seen(seen_now)
    print(f"\nWrote {out_path} ({total} repos surfaced)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
