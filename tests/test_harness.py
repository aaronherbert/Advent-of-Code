"""Offline tests: no network, no API key, no AoC session. Run with:  python3 -m unittest discover -s tests -v"""
import datetime as dt
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="aoc-test-"))
os.environ["AOC_ROOT"] = str(TMP)
os.environ["AOC_RUNS"] = "2"
os.environ.pop("AOC_LANGS", None)
sys.path.insert(0, str(REPO))
shutil.copytree(REPO / "config", TMP / "config")
shutil.copytree(REPO / "harness" / "site", TMP / "site-src", dirs_exist_ok=True)

from harness import aggregate, aocclient, bench, common as c, generate, htmltext  # noqa: E402
from harness.cli import main as cli_main  # noqa: E402

PAGE = """<html><body><a href="/auth/logout">[Log Out]</a><main>
<article class="day-desc"><h2>--- Day 1: Number Cruncher ---</h2>
<p>Add up the <em>numbers</em> in your <code>input</code>.</p>
<pre><code>1
2
3
</code></pre>
<p>Your puzzle answer was <code>6</code>.</p></article>
<article class="day-desc"><h2 id="part2">--- Part Two ---</h2><p>Now square them first.</p>
<p>Your puzzle answer was <code>14</code>.</p>
<p>Both parts of this puzzle are complete! They provide two gold stars: **</p></article>
</main></body></html>"""


def lang(lid):
    return next(l for l in c.languages() if l["id"] == lid)


class HtmlTests(unittest.TestCase):
    def test_parse_page(self):
        r = htmltext.parse_puzzle_page(PAGE)
        self.assertEqual(r["title"], "Number Cruncher")
        self.assertEqual(r["parts"], 2)
        self.assertEqual(r["verified"], ["6", "14"])
        joined = "\n".join(r["text"])
        self.assertIn("```\n1\n2\n3\n```", joined)
        self.assertIn("*numbers*", joined)
        self.assertNotIn("puzzle answer", joined)
        self.assertNotIn("Both parts", joined)

    def test_part_one_only(self):
        one = PAGE.split('<article class="day-desc"><h2 id="part2">')[0] + "</main></body></html>"
        r = htmltext.parse_puzzle_page(one)
        self.assertEqual((r["parts"], r["verified"]), (1, ["6"]))


class AggregateTests(unittest.TestCase):
    def entry(self, out, status="ok", t=0.01):
        return {"status": status, "output": out, "stats": {"median": t, "min": t, "n": 3},
                "max_rss_mb": 10, "build": None}

    def langs(self):
        return [{"id": i, "name": i.title(), "kind": "native", "file": "x"} for i in "abcde"]

    def test_consensus_and_wrong(self):
        results = {"languages": {
            "a": self.entry(["1", "2"], t=0.02), "b": self.entry(["1", "2"], t=0.01),
            "c": self.entry(["1", "3"]), "d": self.entry([], status="build_failed")}}
        v = aggregate.day_view({"parts": 2}, results, self.langs())
        by = {r["id"]: r for r in v["rows"]}
        self.assertEqual(v["expected"][1], {"answer": "2", "source": "consensus"})
        self.assertEqual(by["a"]["verdict"], "correct")
        self.assertEqual(by["c"]["verdict"], "wrong")
        self.assertEqual(by["d"]["verdict"], "build_failed")
        self.assertEqual(by["b"]["rank"], 1)
        self.assertAlmostEqual(by["a"]["slowdown"], 2.0)
        self.assertIsNone(by["c"]["rank"])
        self.assertEqual(set(aggregate.failing_languages(v)), {"c", "d"})

    def test_verified_beats_consensus(self):
        results = {"languages": {"a": self.entry(["9", "9"]), "b": self.entry(["9", "9"]),
                                 "c": self.entry(["1", "2"])}}
        v = aggregate.day_view({"parts": 2, "verified": ["1", "2"]}, results, self.langs())
        by = {r["id"]: r["verdict"] for r in v["rows"]}
        self.assertEqual(by, {"c": "correct", "a": "wrong", "b": "wrong"})

    def test_tie_has_no_consensus(self):
        results = {"languages": {"a": self.entry(["1"]), "b": self.entry(["1"]),
                                 "c": self.entry(["2"]), "d": self.entry(["2"])}}
        v = aggregate.day_view({"parts": 1}, results, self.langs())
        self.assertIsNone(v["expected"][0]["answer"])
        self.assertTrue(all(r["verdict"] == "unchecked" for r in v["rows"]))

    def test_leaderboard(self):
        results = {"languages": {"a": self.entry(["1"], t=0.04), "b": self.entry(["1"], t=0.01),
                                 "c": self.entry(["1"], t=0.02)}}
        v = aggregate.day_view({"parts": 1}, results, self.langs())
        board = aggregate.leaderboard([v, v], self.langs())
        self.assertEqual([r["id"] for r in board], ["b", "c", "a"])
        self.assertEqual(board[0]["wins"], 2)
        self.assertAlmostEqual(board[2]["slowdown"], 4.0)


class SmallTests(unittest.TestCase):
    def test_extract_code(self):
        self.assertEqual(generate.extract_code("Here:\n```python\nprint(1)\n```\nbye"), "print(1)\n")
        self.assertEqual(generate.extract_code("print(2)"), "print(2)\n")

    def test_prompt_mentions_part_availability(self):
        p1 = generate.task_prompt(2026, 1, lang("python"), "Python 3.12", "TEXT", 1)
        p2 = generate.task_prompt(2026, 1, lang("python"), "Python 3.12", "TEXT", 2)
        self.assertIn("Only part 1", p1)
        self.assertIn("Both parts", p2)
        self.assertIn("Python 3.12", p1)

    def test_repair_prompt_does_not_reveal_answers(self):
        info = {"verdict": "wrong", "error": "", "output": ["111", "222"], "wrong_parts": [2]}
        text = generate.repair_prompt(lang("python"), info, c.settings())
        self.assertIn("part 2", text)
        self.assertNotIn("expected", text.lower())

    def test_unlock_calendar(self):
        utc = dt.timezone.utc
        self.assertEqual(c.last_unlocked_day(2026, dt.datetime(2026, 12, 1, 4, 59, tzinfo=utc)), 0)
        self.assertEqual(c.last_unlocked_day(2026, dt.datetime(2026, 12, 1, 5, 0, tzinfo=utc)), 1)
        self.assertEqual(c.last_unlocked_day(2026, dt.datetime(2026, 12, 12, 6, 0, tzinfo=utc)), 12)
        self.assertEqual(c.last_unlocked_day(2026, dt.datetime(2026, 11, 25, 6, 0, tzinfo=utc)), 0)
        self.assertEqual(c.last_unlocked_day(2026, dt.datetime(2027, 1, 3, 6, 0, tzinfo=utc)), 25)

    def test_parse_days(self):
        self.assertEqual(c.parse_days("1-3,7", 2026), [1, 2, 3, 7])
        with self.assertRaises(SystemExit):
            c.parse_days("0,30", 2026)

    def test_scrubbed_env_drops_secrets(self):
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "x", "AOC_SESSION": "y", "MY_TOKEN": "z",
                                           "GITHUB_TOKEN": "t", "PATH_OK": "1"}):
            env = c.scrubbed_env()
        for k in ("ANTHROPIC_API_KEY", "AOC_SESSION", "MY_TOKEN", "GITHUB_TOKEN"):
            self.assertNotIn(k, env)
        self.assertIn("PATH", env)

    def test_every_language_is_well_formed(self):
        ids = set()
        for l in c.languages(include_disabled=True):
            self.assertNotIn(l["id"], ids)
            ids.add(l["id"])
            for k in ("id", "name", "kind", "file", "run", "version", "hint"):
                self.assertTrue(l.get(k), f"{l['id']} missing {k}")
            self.assertIn(l["kind"], ("native", "vm", "interpreted"))
            for s in l.get("scaffold", []):
                self.assertTrue((REPO / "harness" / "templates" / l["id"] / s).exists())
        self.assertEqual(len(ids), 25)


class FetchTests(unittest.TestCase):
    def test_fetch_plans_and_stores_private_data_outside_results(self):
        calls = []

        def fake_get(path, session):
            calls.append(path)
            return (200, PAGE) if not path.endswith("/input") else (200, "1\n2\n3\n")

        with mock.patch.dict(os.environ, {"AOC_SESSION": "abc"}), \
                mock.patch.object(aocclient, "http_get", fake_get), \
                mock.patch.object(c, "last_unlocked_day", lambda y, now=None: 1):
            self.assertEqual(aocclient.cmd_fetch(2026, "auto", False), 0)
        self.assertEqual(calls, ["/2026/day/1", "/2026/day/1/input"])
        meta = json.loads((TMP / "2026" / "day01" / "meta.json").read_text())
        self.assertEqual((meta["title"], meta["parts"], meta["verified"]), ("Number Cruncher", 2, ["6", "14"]))
        plan = json.loads((TMP / ".work" / "plan.json").read_text())
        self.assertEqual(plan["days"], [{"day": 1, "parts": 2}])
        self.assertTrue((TMP / ".work" / "2026" / "day01" / "input.txt").exists())
        self.assertNotIn("1\n2\n3", (TMP / "2026" / "day01" / "meta.json").read_text())


class GenerateRepairFlow(unittest.TestCase):
    """generate -> bench -> repair -> bench with the Claude call mocked out."""

    def test_flow(self):
        day = 3
        wd = TMP / ".work" / "2026" / "day03"
        wd.mkdir(parents=True, exist_ok=True)
        (wd / "puzzle.md").write_text("## Day 3\n\nSum the numbers, then sum their squares.\n")
        (wd / "input.txt").write_text("4\n5\n6\n")  # private input: must never be sent to the API
        (TMP / "2026" / "day03").mkdir(parents=True, exist_ok=True)
        (TMP / "2026" / "day03" / "meta.json").write_text(json.dumps(
            {"year": 2026, "day": 3, "title": "Flow", "parts": 2, "verified": ["15", "77"]}))
        good = {
            "python": "import sys\nn=[int(x) for x in sys.stdin.read().split()]\nprint(sum(n))\nprint(sum(x*x for x in n))\n",
            "javascript": "const n=require('fs').readFileSync(0,'utf8').split(/\\s+/).filter(Boolean).map(Number);\n"
                          "console.log(n.reduce((a,b)=>a+b,0));console.log(n.reduce((a,b)=>a+b*b,0));\n",
        }
        broken_python = "import sys\nsys.exit(3)\n"
        sent = []
        attempt = {"python": 0}

        def fake_claude(messages, cfg):
            sent.append(json.dumps(messages))
            lid = "python" if "Language: Python" in messages[0]["content"] else "javascript"
            if lid == "python" and len(messages) == 1:
                return "```python\n" + broken_python + "```"
            return "```\n" + good[lid] + "```"

        only = [lang("python"), lang("javascript")]
        with mock.patch.object(generate, "call_claude", fake_claude):
            self.assertEqual(generate.cmd_generate(2026, [day], only, False, False, False), 0)
            meta = json.loads((TMP / "2026" / "day03" / "meta.json").read_text())
            self.assertEqual(meta["parts_generated"], 2)
            self.assertTrue((TMP / "2026" / "day03" / "python" / "solution.py").exists())
            bench.cmd_bench(2026, [day], only, False)
            res = json.loads((TMP / "2026" / "day03" / "results.json").read_text())["languages"]
            self.assertEqual(res["python"]["status"], "runtime_error")
            self.assertEqual(res["javascript"]["status"], "ok")
            # repair round: only the broken language is re-requested, with 3 messages of history
            before = len(sent)
            self.assertEqual(generate.cmd_generate(2026, [day], only, True, False, False), 0)
            self.assertEqual(len(sent) - before, 1)
            self.assertIn("did not work", sent[-1])
            bench.cmd_bench(2026, [day], only, True)
        res = json.loads((TMP / "2026" / "day03" / "results.json").read_text())["languages"]
        self.assertEqual(res["python"]["status"], "ok")
        self.assertEqual(res["python"]["repairs"], 1)
        self.assertEqual(res["python"]["output"], ["15", "77"])
        self.assertFalse(any("4\\n5\\n6" in m for m in sent), "puzzle input leaked into an API request")
        self.assertFalse(any("15" in m and "77" in m for m in sent), "accepted answers leaked into a prompt")


class EndToEnd(unittest.TestCase):
    """Bench real fixture programs in whichever languages this machine has, then build the site."""

    @classmethod
    def setUpClass(cls):
        day = TMP / "2026" / "day02"
        for sub in (REPO / "tests" / "fixtures" / "solutions").iterdir():
            shutil.copytree(sub, day / sub.name, dirs_exist_ok=True)
        nums = [(i * 7919) % 1000 - 300 for i in range(3000)]
        wd = TMP / ".work" / "2026" / "day02"
        wd.mkdir(parents=True, exist_ok=True)
        (wd / "input.txt").write_text("\n".join(map(str, nums)) + "\n")
        cls.a = sum(nums)
        cls.b = sum(x * x for x in nums)
        (day / "meta.json").write_text(json.dumps({"year": 2026, "day": 2, "title": "Fixture", "parts": 2}))
        rc = cli_main(["bench", "--year", "2026", "--days", "2"])
        cls.rc = rc
        cls.results = json.loads((day / "results.json").read_text())["languages"]

    def test_bench_exit_code(self):
        self.assertEqual(self.rc, 0)

    def test_python_result(self):
        r = self.results["python"]
        self.assertEqual(r["status"], "ok")
        self.assertEqual(r["output"], [str(self.a), str(self.b)])
        self.assertEqual(r["stats"]["n"], 2)
        self.assertGreater(r["stats"]["median"], 0)
        self.assertGreater(r["max_rss_mb"], 1)

    def test_crash_is_reported(self):
        if self.results["ruby"]["status"] == "no_toolchain":
            self.skipTest("ruby not installed")
        self.assertEqual(self.results["ruby"]["status"], "runtime_error")
        self.assertIn("boom", self.results["ruby"]["error"])

    def test_missing_toolchain_is_reported(self):
        # No fixture exists for lua, so it must be absent rather than failed.
        self.assertNotIn("lua", self.results)

    def test_site_build_and_verdicts(self):
        self.assertEqual(cli_main(["site", "--out", "dist"]), 0)
        dist = TMP / "dist"
        data = json.loads((dist / "data.json").read_text())
        day = next(d for y in data["years"] for d in y["days"] if d["day"] == 2)
        by = {r["id"]: r for r in day["rows"]}
        self.assertEqual(by["python"]["verdict"], "correct")
        if by.get("perl", {}).get("status") == "ok":
            self.assertEqual(by["perl"]["verdict"], "wrong")
        self.assertEqual(day["expected"][0]["answer"], str(self.a))
        self.assertTrue((dist / "index.html").exists())
        self.assertTrue((dist / "src" / "2026" / "day02" / "python" / "solution.py").exists())
        self.assertEqual(data["years"][0]["leaderboard"][0]["id"] in by, True)

    def test_collect_only_publishable_files(self):
        self.assertEqual(cli_main(["collect", "--out", "out"]), 0)
        files = {str(p.relative_to(TMP / "out")) for p in (TMP / "out").rglob("*") if p.is_file()}
        self.assertIn("2026/day02/results.json", files)
        self.assertIn("2026/day02/python/solution.py", files)
        self.assertFalse(any(f.startswith(".work") or f.endswith("input.txt") for f in files))

    def test_only_changed_skips_unchanged(self):
        before = (TMP / "2026" / "day02" / "results.json").read_text()
        cli_main(["bench", "--year", "2026", "--days", "2", "--only-changed", "--langs", "python"])
        after = (TMP / "2026" / "day02" / "results.json").read_text()
        self.assertEqual(before, after)

    def test_report_runs(self):
        self.assertEqual(cli_main(["report", "--year", "2026"]), 0)


def tearDownModule():
    shutil.rmtree(TMP, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
