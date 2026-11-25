"""`fetch`: read puzzle pages and personal inputs from adventofcode.com.

Runs in a CI step that holds the AOC_SESSION secret and nothing else that executes
generated code. Puzzle text and inputs go to .work/ (git-ignored, never published).
"""
from __future__ import annotations

import datetime as dt
import os
import urllib.error
import urllib.request

from . import common as c
from .htmltext import parse_puzzle_page

BASE = "https://adventofcode.com"
RECHECK_MINUTES = 60


class AocError(RuntimeError):
    pass


def _user_agent() -> str:
    ua = os.environ.get("AOC_USER_AGENT")
    if ua:
        return ua
    repo = os.environ.get("GITHUB_REPOSITORY") or c.settings().get("repo") or "local checkout"
    return f"github.com/{repo} advent-of-code multi-language harness (one request per puzzle page/input, cached)"


def http_get(path: str, session: str | None) -> tuple[int, str]:
    req = urllib.request.Request(BASE + path, headers={"User-Agent": _user_agent()})
    if session:
        req.add_header("Cookie", f"session={session}")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")


def _needs_check(meta: dict, force: bool) -> bool:
    if force or not meta:
        return True
    complete = meta.get("parts", 0) == 2 and len(meta.get("verified", [])) == 2
    if complete:
        return False
    checked = meta.get("checked_at")
    if not checked:
        return True
    age = dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(checked)
    return age > dt.timedelta(minutes=RECHECK_MINUTES)


def _has_solutions(year: int, day: int) -> bool:
    return any(c.source_path(year, day, lang).exists() for lang in c.languages())


def cmd_fetch(year: int, days_spec: str | None, force: bool) -> int:
    session = os.environ.get("AOC_SESSION", "").strip()
    last = c.last_unlocked_day(year)
    if days_spec in (None, "", "auto"):
        days = list(range(1, last + 1))
    else:
        days = [d for d in c.parse_days(days_spec, year) if d <= max(last, 25)]
    plan = []

    for day in days:
        ddir = c.day_dir(year, day)
        wdir = c.work_dir(year, day)
        meta = c.read_json(ddir / "meta.json", {})
        have_local = (wdir / "puzzle.md").exists() and (wdir / "input.txt").exists()

        if have_local and not session:
            # Offline / local development with hand-placed files.
            parts = meta.get("parts") or 1
            plan.append({"day": day, "parts": parts})
            continue

        if not _needs_check(meta, force):
            continue
        if not session:
            c.log(f"day {day}: AOC_SESSION is not set, skipping")
            continue

        status, page = http_get(f"/{year}/day/{day}", session)
        if status == 404:
            c.log(f"day {day}: not unlocked yet (404)")
            continue
        if status != 200:
            c.log(f"day {day}: puzzle page returned HTTP {status}, skipping")
            continue
        parsed = parse_puzzle_page(page)
        if not parsed["parts"]:
            c.log(f"day {day}: could not find puzzle text on the page, skipping")
            continue
        if "[Log In]" in page and "[Log Out]" not in page:
            raise AocError("AOC_SESSION looks expired: the puzzle page shows the logged-out view")

        new_meta = dict(meta)
        new_meta.update({
            "year": year, "day": day, "title": parsed["title"] or meta.get("title", ""),
            "parts": parsed["parts"], "verified": parsed["verified"], "checked_at": c.now_iso(),
        })
        c.write_json(ddir / "meta.json", new_meta)

        needs_generation = (force or not _has_solutions(year, day)
                            or meta.get("parts_generated", 0) < parsed["parts"])
        if not needs_generation:
            continue

        status, text = http_get(f"/{year}/day/{day}/input", session)
        if status != 200:
            raise AocError(f"day {day}: input request returned HTTP {status} (expired AOC_SESSION?)")
        wdir.mkdir(parents=True, exist_ok=True)
        puzzle = "\n\n".join(parsed["text"])
        (wdir / "puzzle.md").write_text(puzzle + "\n", encoding="utf-8")
        (wdir / "input.txt").write_text(text, encoding="utf-8")
        plan.append({"day": day, "parts": parsed["parts"]})
        c.log(f"day {day}: {parsed['title']!r}, {parsed['parts']} part(s) available, queued for generation")

    c.write_json(c.ROOT / ".work" / "plan.json", {"year": year, "days": plan})
    c.log(f"plan: {len(plan)} day(s) to process: {[p['day'] for p in plan]}")
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as fh:
            fh.write(f"days={','.join(str(p['day']) for p in plan)}\n")
            fh.write(f"count={len(plan)}\n")
    return 0
