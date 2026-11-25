"""Decide what each language's answer means, and roll results up into leaderboards.

Ground truth for a part is, in order of preference:
  1. the answer adventofcode.com accepted (read back from the puzzle page after you submit it), or
  2. consensus: the answer most languages agree on (needs >= 2 votes and a strict plurality).
"""
from __future__ import annotations

import math
import statistics
from collections import Counter

FAILED = {"build_failed", "runtime_error", "timeout", "bad_output"}
NO_ANSWER = {"", "-"}


def _consensus(answers: list[str]) -> str | None:
    counts = Counter(a for a in answers if a not in NO_ANSWER).most_common(2)
    if not counts:
        return None
    top = counts[0]
    if top[1] < 2:
        return None
    if len(counts) > 1 and counts[1][1] == top[1]:
        return None
    return top[0]


def day_view(meta: dict, results: dict, languages: list[dict]) -> dict:
    """Combine meta.json + results.json into the structure used by the site and the repair loop."""
    parts = max(1, int(meta.get("parts", 1) or 1))
    verified = list(meta.get("verified", []))
    entries = results.get("languages", {})

    expected: list[dict] = []
    for i in range(parts):
        votes = [e["output"][i] if len(e.get("output", [])) > i else ""
                 for e in entries.values() if e.get("status") == "ok"]
        if i < len(verified):
            expected.append({"answer": verified[i], "source": "verified"})
        else:
            cons = _consensus(votes)
            expected.append({"answer": cons, "source": "consensus" if cons else None})

    rows = []
    for lang in languages:
        e = entries.get(lang["id"])
        if not e:
            continue
        status = e.get("status", "missing")
        out = list(e.get("output", []))
        out += [""] * (parts - len(out))
        per_part = []
        for i in range(parts):
            want = expected[i]["answer"]
            if status != "ok":
                per_part.append(None)
            elif want is None:
                per_part.append(None)
            else:
                per_part.append(out[i] == want)
        if status in FAILED or status == "no_toolchain":
            verdict = status
        elif any(p is False for p in per_part):
            verdict = "wrong"
        elif per_part and all(p is True for p in per_part):
            verdict = "correct"
        else:
            verdict = "unchecked"
        stats = e.get("stats") or {}
        rows.append({
            "id": lang["id"], "name": lang["name"], "kind": lang.get("kind", ""),
            "file": lang["file"], "status": status, "verdict": verdict,
            "output": out[:parts], "per_part": per_part,
            "median": stats.get("median"), "min": stats.get("min"), "stdev": stats.get("stdev"),
            "cold": stats.get("cold"), "runs": stats.get("n"),
            "build_seconds": (e.get("build") or {}).get("seconds"),
            "rss_mb": e.get("max_rss_mb"), "version": e.get("version"),
            "error": e.get("error", ""), "repairs": e.get("repairs", 0),
        })

    eligible = [r for r in rows if r["verdict"] in ("correct", "unchecked") and r["median"] is not None]
    best_t = min((r["median"] for r in eligible), default=None)
    best_m = min((r["rss_mb"] for r in eligible if r["rss_mb"]), default=None)
    ranked = sorted(eligible, key=lambda r: r["median"])
    for r in rows:
        r["rank"] = None
        r["slowdown"] = None
        r["mem_ratio"] = None
    for pos, r in enumerate(ranked, 1):
        r["rank"] = pos
        r["slowdown"] = max(r["median"], 1e-4) / max(best_t, 1e-4)
        if best_m and r["rss_mb"]:
            r["mem_ratio"] = r["rss_mb"] / best_m
    rows.sort(key=lambda r: (r["rank"] is None, r["rank"] or 0, r["name"]))

    return {
        "year": meta.get("year"), "day": meta.get("day"), "title": meta.get("title", ""),
        "parts": parts, "expected": expected, "rows": rows,
        "runner": results.get("runner", {}), "generated_at": results.get("generated_at"),
        "model": meta.get("model"),
    }


def failing_languages(view: dict) -> dict[str, dict]:
    """Languages worth a repair attempt, with the reason the model should be told."""
    out = {}
    for r in view["rows"]:
        if r["verdict"] in FAILED:
            out[r["id"]] = {"verdict": r["verdict"], "error": r["error"], "output": r["output"]}
        elif r["verdict"] == "wrong":
            wrong = [i + 1 for i, ok in enumerate(r["per_part"]) if ok is False]
            out[r["id"]] = {"verdict": "wrong", "error": "", "output": r["output"], "wrong_parts": wrong}
    return out


def _geomean(values: list[float]) -> float | None:
    values = [v for v in values if v and v > 0]
    if not values:
        return None
    return math.exp(sum(math.log(v) for v in values) / len(values))


def leaderboard(views: list[dict], languages: list[dict]) -> list[dict]:
    """One row per language across the given days."""
    acc = {l["id"]: {"id": l["id"], "name": l["name"], "kind": l.get("kind", ""),
                     "days": 0, "ok": 0, "wins": 0, "failed": 0, "wrong": 0,
                     "slow": [], "mem": [], "medians": [], "builds": []} for l in languages}
    for v in views:
        for r in v["rows"]:
            a = acc.get(r["id"])
            if a is None:
                continue
            a["days"] += 1
            if r["verdict"] in ("correct", "unchecked"):
                a["ok"] += 1
                if r["slowdown"]:
                    a["slow"].append(r["slowdown"])
                if r["mem_ratio"]:
                    a["mem"].append(r["mem_ratio"])
                if r["median"] is not None:
                    a["medians"].append(r["median"])
                if r["build_seconds"]:
                    a["builds"].append(r["build_seconds"])
                if r["rank"] == 1:
                    a["wins"] += 1
            elif r["verdict"] == "wrong":
                a["wrong"] += 1
            elif r["verdict"] in FAILED:
                a["failed"] += 1
    rows = []
    for a in acc.values():
        if not a["days"]:
            continue
        rows.append({
            "id": a["id"], "name": a["name"], "kind": a["kind"], "days": a["days"],
            "ok": a["ok"], "wins": a["wins"], "wrong": a["wrong"], "failed": a["failed"],
            "slowdown": _geomean(a["slow"]), "mem_ratio": _geomean(a["mem"]),
            "median_seconds": statistics.median(a["medians"]) if a["medians"] else None,
            "build_seconds": statistics.median(a["builds"]) if a["builds"] else None,
        })
    rows.sort(key=lambda r: (r["slowdown"] is None, r["slowdown"] or 0, r["name"]))
    return rows
