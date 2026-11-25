"""Command line entry point: python -m harness <command>."""
from __future__ import annotations

import argparse
import shutil
import sys

from . import common as c


def _doctor(_args) -> int:
    langs = c.languages()
    width = max(len(l["name"]) for l in langs)
    missing = 0
    versions = {}
    for lang in langs:
        v = c.toolchain_version(lang)
        versions[lang["id"]] = v
        missing += v is None
        print(f"{lang['name']:<{width}}  {v or 'MISSING'}")
    c.write_json(c.ROOT / ".work" / "toolchains.json", versions)
    print(f"\n{len(langs) - missing}/{len(langs)} toolchains available")
    return 0


def _collect(args) -> int:
    """Copy only publishable files (sources, meta.json, results.json) for upload as a CI artifact."""
    out = c.ROOT / args.out
    if out.exists():
        shutil.rmtree(out)
    n = 0
    for year in c.all_years():
        for day in c.days_with_data(year):
            ddir = c.day_dir(year, day)
            files = [ddir / "meta.json", ddir / "results.json"]
            files += [c.source_path(year, day, l) for l in c.languages(include_disabled=True)]
            for f in files:
                # Generated code runs next to these files: never follow symlinks or ship oversized files.
                if f.is_symlink() or not f.is_file() or f.stat().st_size > 1_000_000:
                    continue
                if f.exists():
                    dst = out / f.relative_to(c.ROOT)
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy(f, dst)
                    n += 1
    print(f"collected {n} file(s) into {out}")
    return 0


def _report(args) -> int:
    from .sitebuild import build_views
    from .aggregate import leaderboard
    langs = c.languages(include_disabled=True)
    views = build_views(langs)
    year = args.year or c.default_year()
    vs = views.get(year, [])
    if not vs:
        print(f"no results for {year}")
        return 0
    for v in vs:
        exp = ", ".join(f"p{i + 1}={e['answer'] or '?'}({e['source'] or 'unknown'})" for i, e in enumerate(v["expected"]))
        print(f"\nDay {v['day']}: {v['title']}   expected: {exp}")
        for r in v["rows"]:
            t = f"{r['median'] * 1000:9.1f} ms" if r["median"] is not None else "         -  "
            m = f"{r['rss_mb']:7.1f} MB" if r["rss_mb"] else "      -  "
            print(f"  {r['rank'] or '-':>3}  {r['name']:<11} {r['verdict']:<14} {t} {m}  {' | '.join(r['output'])}")
    print("\nLeaderboard (geometric-mean slowdown vs fastest correct solution per day)")
    for i, r in enumerate(leaderboard(vs, langs), 1):
        s = f"{r['slowdown']:.2f}x" if r["slowdown"] else "-"
        print(f"  {i:>2}. {r['name']:<11} {s:>9}  ok {r['ok']}/{r['days']}  wins {r['wins']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="harness", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    def common_args(sp, days=True, langs=False):
        sp.add_argument("--year", type=int, default=None, help="puzzle year (default: current year, US Eastern)")
        if days:
            sp.add_argument("--days", default="auto", help="'auto' (from the fetch plan), 'all', or e.g. '1-5,8'")
        if langs:
            sp.add_argument("--langs", default=None, help="comma-separated language ids")

    sp = sub.add_parser("doctor", help="list which language toolchains are installed")
    sp.set_defaults(fn=_doctor)

    sp = sub.add_parser("fetch", help="read puzzle pages/inputs (needs AOC_SESSION) and write the plan")
    common_args(sp)
    sp.add_argument("--force", action="store_true", help="re-check and regenerate even if up to date")
    sp.set_defaults(fn=lambda a: __import__("harness.aocclient", fromlist=["x"]).cmd_fetch(
        a.year or c.default_year(), a.days, a.force))

    sp = sub.add_parser("generate", help="ask Claude for solutions (needs ANTHROPIC_API_KEY)")
    common_args(sp, langs=True)
    sp.add_argument("--repair", action="store_true", help="fix failing or wrong solutions instead")
    sp.add_argument("--force", action="store_true", help="regenerate even if a solution file exists")
    sp.add_argument("--all-languages", action="store_true",
                    help="also generate for languages whose toolchain is not installed here")

    def _gen(a):
        from .generate import cmd_generate
        year = a.year or c.default_year()
        return cmd_generate(year, c.parse_days(a.days, year), c.select_languages(a.langs),
                            a.repair, a.force, a.all_languages)
    sp.set_defaults(fn=_gen)

    sp = sub.add_parser("bench", help="build and time every solution (run this step with no secrets)")
    common_args(sp, langs=True)
    sp.add_argument("--only-changed", action="store_true", help="skip solutions already benchmarked in this run")

    def _bench(a):
        from .bench import cmd_bench
        year = a.year or c.default_year()
        return cmd_bench(year, c.parse_days(a.days, year), c.select_languages(a.langs), a.only_changed)
    sp.set_defaults(fn=_bench)

    sp = sub.add_parser("collect", help="gather publishable files into a folder for CI artifacts")
    sp.add_argument("--out", default="out")
    sp.set_defaults(fn=_collect)

    sp = sub.add_parser("site", help="build the GitHub Pages site")
    sp.add_argument("--out", default="dist")
    sp.set_defaults(fn=lambda a: __import__("harness.sitebuild", fromlist=["x"]).cmd_site(a.out))

    sp = sub.add_parser("report", help="print results and the leaderboard in the terminal")
    sp.add_argument("--year", type=int, default=None)
    sp.set_defaults(fn=_report)

    args = p.parse_args(argv)
    try:
        return int(args.fn(args) or 0)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
