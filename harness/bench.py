"""`bench`: build every language's solution and time it against the puzzle input.

This step runs generated code, so it must run in a CI step that holds no secrets.
Child processes also get a scrubbed environment as a second line of defence.

What is measured, per language:
  * build wall time (compiled languages)
  * wall time of the whole process, startup included, over several runs
    (run 1 is a cold/warm-up run and is reported separately as `cold`)
  * peak resident memory and CPU time, from wait4() rusage
"""
from __future__ import annotations

import os
import platform
import shlex
import shutil
import signal
import statistics
import subprocess
import sys
import tempfile
import time

from . import common as c

MAX_OUTPUT = 1_000_000


def run_once(argv: list[str], cwd, stdin_path, timeout: float, env: dict) -> dict:
    """Run one process, returning timing, rusage and captured output."""
    with open(stdin_path, "rb") as fin, tempfile.TemporaryFile() as fout, tempfile.TemporaryFile() as ferr:
        t0 = time.perf_counter()
        try:
            proc = subprocess.Popen(argv, stdin=fin, stdout=fout, stderr=ferr, cwd=cwd, env=env,
                                    start_new_session=True)
        except (FileNotFoundError, PermissionError) as exc:
            return {"exit": 127, "seconds": 0.0, "stdout": "", "stderr": str(exc), "timed_out": False,
                    "user": 0.0, "sys": 0.0, "rss_mb": 0.0}
        timed_out = False
        while True:
            pid, status, ru = os.wait4(proc.pid, os.WNOHANG)
            if pid:
                break
            if time.perf_counter() - t0 > timeout:
                timed_out = True
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                pid, status, ru = os.wait4(proc.pid, 0)
                break
            time.sleep(0.001)
        elapsed = time.perf_counter() - t0
        proc.returncode = os.waitstatus_to_exitcode(status)
        fout.seek(0)
        ferr.seek(0)
        stdout = fout.read(MAX_OUTPUT).decode("utf-8", "replace")
        stderr = ferr.read(MAX_OUTPUT).decode("utf-8", "replace")
    rss = ru.ru_maxrss / (1024 * 1024 if sys.platform == "darwin" else 1024)
    return {"exit": proc.returncode, "seconds": elapsed, "stdout": stdout, "stderr": stderr,
            "timed_out": timed_out, "user": ru.ru_utime, "sys": ru.ru_stime, "rss_mb": rss}


def _cpu_model() -> str:
    try:
        with open("/proc/cpuinfo", encoding="utf-8") as fh:
            for line in fh:
                if line.lower().startswith("model name"):
                    return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor() or platform.machine()


def runner_info() -> dict:
    return {"os": platform.platform(), "cpu": _cpu_model(), "cores": os.cpu_count(),
            "python": platform.python_version(), "ci": bool(os.environ.get("GITHUB_ACTIONS")),
            "run_id": os.environ.get("GITHUB_RUN_ID", "")}


def _parse_output(stdout: str, parts: int) -> tuple[list[str], bool]:
    lines = [l.strip()[:200] for l in stdout.strip().splitlines() if l.strip()]
    answers = lines[:2]
    ok = len(answers) >= parts
    answers += [""] * (2 - len(answers))
    return answers[:parts], ok


def _stats(times: list[float], cold: float) -> dict:
    return {
        "n": len(times), "min": min(times), "median": statistics.median(times),
        "mean": statistics.fmean(times), "stdev": statistics.stdev(times) if len(times) > 1 else 0.0,
        "cold": cold,
    }


def bench_language(year: int, day: int, lang: dict, parts: int, input_path, cfg: dict,
                   previous: dict | None) -> dict:
    src = c.source_path(year, day, lang)
    entry: dict = {"sha": c.sha256_file(src), "version": None, "repairs": (previous or {}).get("repairs", 0)}
    version = c.toolchain_version(lang)
    if version is None:
        entry.update(status="no_toolchain", error=f"{lang['name']} toolchain not installed on this runner")
        return entry
    entry["version"] = version

    bdir = c.build_dir(year, day, lang["id"])
    c.copytree_clean(src.parent, bdir)
    for name in lang.get("scaffold", []):
        shutil.copy(c.HARNESS_DIR / "templates" / lang["id"] / name, bdir / name)

    env = c.scrubbed_env()
    if lang.get("build"):
        t0 = time.perf_counter()
        code, log, timed_out = c.run_capture(lang["build"], cwd=bdir, shell=True, env=env,
                                             timeout=cfg["build_timeout_seconds"])
        seconds = time.perf_counter() - t0
        entry["build"] = {"seconds": seconds, "ok": code == 0, "log": c.tail(log, 1200)}
        if code != 0:
            entry.update(status="build_failed",
                         error=c.tail(log, 1500) + ("\n(build timed out)" if timed_out else ""))
            return entry

    argv = shlex.split(lang["run"])
    timeout = cfg["run_timeout_seconds"]
    first = run_once(argv, bdir, input_path, timeout, env)
    entry["max_rss_mb"] = first["rss_mb"]
    if first["timed_out"]:
        entry.update(status="timeout", error=f"exceeded {timeout}s on the first run")
        return entry
    if first["exit"] != 0:
        entry.update(status="runtime_error",
                     error=f"exit code {first['exit']}\n" + c.tail(first["stderr"] or first["stdout"], 1500))
        return entry
    answers, ok = _parse_output(first["stdout"], parts)
    entry["output"] = answers
    if not ok:
        entry.update(status="bad_output",
                     error=f"expected {parts} answer line(s) on stdout, got:\n" + c.tail(first["stdout"], 400))
        return entry

    runs = [first]
    times: list[float] = []
    if first["seconds"] > cfg["slow_first_run_seconds"]:
        times = [first["seconds"]]
    else:
        for _ in range(max(1, cfg["runs"])):
            r = run_once(argv, bdir, input_path, timeout, env)
            if r["timed_out"] or r["exit"] != 0:
                entry.update(status="runtime_error", error="a repeat run failed: " + c.tail(r["stderr"], 800))
                return entry
            if _parse_output(r["stdout"], parts)[0] != answers:
                entry.update(status="runtime_error", error="output changed between runs (non-deterministic)")
                return entry
            runs.append(r)
            times.append(r["seconds"])
    entry["max_rss_mb"] = max(r["rss_mb"] for r in runs)
    entry["stats"] = _stats(times, first["seconds"])
    entry["cpu"] = {"user": statistics.median(r["user"] for r in runs),
                    "sys": statistics.median(r["sys"] for r in runs)}
    entry["status"] = "ok"
    entry["error"] = ""
    return entry


def cmd_bench(year: int, days: list[int], langs: list[dict], only_changed: bool) -> int:
    cfg = c.settings()
    if not days:
        c.log("bench: nothing to do (no days selected)")
        return 0
    failures = 0
    for day in days:
        ddir = c.day_dir(year, day)
        input_path = c.work_dir(year, day) / "input.txt"
        if not input_path.exists():
            c.log(f"day {day}: no input at {input_path}; run `fetch` first")
            failures += 1
            continue
        meta = c.read_json(ddir / "meta.json", {})
        parts = max(1, int(meta.get("parts", 1) or 1))
        results = c.read_json(ddir / "results.json", {"languages": {}})
        results.setdefault("languages", {})
        state = c.read_json(c.work_dir(year, day) / "state.json", {})
        results["runner"] = runner_info()
        for lang in langs:
            src = c.source_path(year, day, lang)
            if not src.exists():
                continue
            prev = results["languages"].get(lang["id"])
            repairs = state.get("repairs", {}).get(lang["id"], 0)
            if (only_changed and prev and prev.get("sha") == c.sha256_file(src)
                    and prev.get("run_id") == os.environ.get("GITHUB_RUN_ID", "")):
                continue
            c.log(f"day {day}: {lang['name']} …")
            prev = dict(prev or {}, repairs=repairs)
            entry = bench_language(year, day, lang, parts, input_path, cfg, prev)
            entry["repairs"] = repairs
            entry["run_id"] = os.environ.get("GITHUB_RUN_ID", "")
            results["languages"][lang["id"]] = entry
            t = (entry.get("stats") or {}).get("median")
            c.log(f"day {day}: {lang['name']}: {entry['status']}"
                  + (f" {t * 1000:.1f} ms" if t is not None else ""))
            results["generated_at"] = c.now_iso()
            c.write_json(ddir / "results.json", results)
        shutil.rmtree(c.ROOT / ".build" / str(year) / f"day{day:02d}", ignore_errors=True)
    return 1 if failures else 0
