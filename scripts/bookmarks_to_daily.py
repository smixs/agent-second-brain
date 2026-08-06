#!/usr/bin/env python3
"""Pull X/Twitter bookmarks into the vault's daily note (autograph capture step).

Idempotent: each bookmark carries a `<!-- bm:<tweet_id> -->` marker; re-runs skip
any id already present in ANY daily file. Then run autograph's daily.py extract
to turn the day's captures into cards.

Usage:
  bookmarks_to_daily.py [YYYY-MM-DD]   # default: today
  bookmarks_to_daily.py --self-check
"""
import json
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

VAULT = Path.home() / "dev/my/agent-second-brain/vault"
DAILY = VAULT / "daily"
SECTION = "## Bookmarks"


def fetch_bookmarks():
    out = subprocess.run(
        ["x-cli", "--json", "me", "bookmarks", "--max", "100"],
        capture_output=True, text=True, check=True,
    ).stdout
    return json.loads(out)


def existing_ids():
    ids = set()
    for f in DAILY.glob("*.md"):
        ids.update(re.findall(r"bm:(\d+)", f.read_text(encoding="utf-8")))
    return ids


def fmt(bm):
    tid = str(bm["id"])
    text = " ".join(bm.get("text", "").split())
    urls = bm.get("entities", {}).get("urls", [])
    # last expanded_url is the real link (t.co ones come first)
    link_out = next((u["expanded_url"] for u in reversed(urls)
                     if u.get("expanded_url") and "twitter.com" not in u["expanded_url"]
                     and "x.com" not in u["expanded_url"]), "")
    d = bm.get("created_at", "")[:10]
    post = f"https://x.com/i/status/{tid}"
    line = f"- {text}" if text else "- (no text)"
    if link_out:
        line += f" — {link_out}"
    line += f" ([post]({post}), {d}) <!-- bm:{tid} -->"
    return line


def write_daily(day, new_lines):
    f = DAILY / f"{day}.md"
    if f.exists():
        body = f.read_text(encoding="utf-8")
    else:
        body = f"# {day}\n\n<!-- Daily file for {day} -->\n"
    if SECTION not in body:
        body = body.rstrip() + f"\n\n{SECTION}\n"
    body = body.rstrip() + "\n" + "\n".join(new_lines) + "\n"
    f.write_text(body, encoding="utf-8")
    return f


def main():
    if "--self-check" in sys.argv:
        bm = {"id": 42, "text": "hello  world\n", "created_at": "2026-07-16T00:00:00.000Z",
              "entities": {"urls": [
                  {"expanded_url": "https://t.co/x"},
                  {"expanded_url": "https://ui-skills.com/foo"}]}}
        line = fmt(bm)
        assert "bm:42" in line and "hello world" in line and "ui-skills.com/foo" in line, line
        assert "https://x.com/i/status/42" in line, line
        print("self-check ok:", line)
        return

    day = next((a for a in sys.argv[1:] if re.fullmatch(r"\d{4}-\d\d-\d\d", a)), date.today().isoformat())
    seen = existing_ids()
    bookmarks = fetch_bookmarks()
    new = [fmt(b) for b in bookmarks if str(b["id"]) not in seen]
    if not new:
        print(f"no new bookmarks ({len(bookmarks)} fetched, all already captured)")
        return
    f = write_daily(day, new)
    print(f"+{len(new)} bookmarks → {f}  ({len(bookmarks)} fetched, {len(bookmarks)-len(new)} skipped)")


if __name__ == "__main__":
    main()
