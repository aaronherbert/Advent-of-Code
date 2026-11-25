"""`site`: build the static GitHub Pages site into dist/ from the committed results."""
from __future__ import annotations

import os
import shutil
from pathlib import Path

from . import common as c
from .aggregate import day_view, leaderboard


def build_views(langs: list[dict]) -> dict[int, list[dict]]:
    out: dict[int, list[dict]] = {}
    for year in c.all_years():
        views = []
        for day in c.days_with_data(year):
            ddir = c.day_dir(year, day)
            meta = c.read_json(ddir / "meta.json", {})
            results = c.read_json(ddir / "results.json")
            if not results or not results.get("languages"):
                continue
            meta.setdefault("year", year)
            meta.setdefault("day", day)
            views.append(day_view(meta, results, langs))
        if views:
            out[year] = views
    return out


def cmd_site(out_dir: str) -> int:
    langs = c.languages(include_disabled=True)
    views_by_year = build_views(langs)
    dist = c.ROOT / out_dir
    if dist.exists():
        shutil.rmtree(dist)
    shutil.copytree(c.HARNESS_DIR / "site", dist)

    all_views = [v for vs in views_by_year.values() for v in vs]
    repo = os.environ.get("GITHUB_REPOSITORY") or c.settings().get("repo") or ""
    data = {
        "generated_at": c.now_iso(),
        "repo": repo,
        "languages": [{"id": l["id"], "name": l["name"], "kind": l.get("kind", ""), "file": l["file"]}
                      for l in langs],
        "overall": leaderboard(all_views, langs),
        "years": [{"year": y, "leaderboard": leaderboard(vs, langs), "days": vs}
                  for y, vs in sorted(views_by_year.items(), reverse=True)],
    }
    c.write_json(dist / "data.json", data)

    for view in all_views:
        for row in view["rows"]:
            src = c.day_dir(view["year"], view["day"]) / row["id"] / row["file"]
            if src.exists():
                dst = dist / "src" / str(view["year"]) / f"day{view['day']:02d}" / row["id"] / row["file"]
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(src, dst)
    (dist / ".nojekyll").write_text("", encoding="utf-8")
    c.log(f"site: wrote {dist} ({len(all_views)} day(s) across {len(views_by_year)} year(s))")
    return 0
