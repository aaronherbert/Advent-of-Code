"""`generate`: ask Claude for a solution in every language, and repair broken ones.

Backends: `claude-code` (default; headless Claude Code CLI on your subscription) or `api` (Anthropic API key).

Only the puzzle text (and, when repairing, compiler/runtime error output) is sent to the
API. The personal puzzle input is never sent, and repair prompts never reveal the expected
answer, only that the program's answer was judged wrong.
"""
from __future__ import annotations

import json
import os
import random
import re
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

from . import common as c
from .aggregate import day_view, failing_languages

API_URL = "https://api.anthropic.com/v1/messages"

SYSTEM = """You are an expert competitive programmer solving Advent of Code puzzles. You write a complete, correct, reasonably fast, idiomatic single-file program in the language you are asked for.

Program contract (strict, a harness depends on it):
- Read the entire puzzle input from standard input. Do not open any files and do not use the network.
- Write exactly two lines to standard output: the answer to part 1, then the answer to part 2. Nothing else on stdout (no labels, no debug output, no blank lines). Debug output, if any, goes to stderr.
- If only part 1 of the puzzle is available, print the part 1 answer and then a single `-` as the second line.
- Answers are printed as plain text exactly as Advent of Code expects them (integers without separators or exponents).
- Be deterministic: no randomness, no timing dependence.
- Use only the language's standard library and the toolchain described in the request. No third-party packages.
- Never hard-code answers. The solution must work for any valid puzzle input of this puzzle.
- Think about the input's real size: choose algorithms that finish in a few seconds at most, since the runtime of this program is benchmarked against the same solution written in other languages. Prefer clear, idiomatic code of the language over micro-hacks.

Reply with the full source file in ONE fenced code block and nothing else."""


# ------------------------------------------------------------------ API

def call_claude(messages: list[dict], cfg: dict) -> str:
    """Send the conversation to Claude using the configured backend."""
    backend = cfg.get("backend", "claude-code")
    if backend == "claude-code":
        return call_claude_code(messages, cfg)
    if backend == "api":
        return call_anthropic_api(messages, cfg)
    raise SystemExit(f"unknown backend {backend!r} (use 'claude-code' or 'api')")


def render_transcript(messages: list[dict]) -> str:
    """Flatten a short conversation into one prompt for `claude -p`."""
    if len(messages) == 1:
        return messages[0]["content"]
    labels = {"user": "USER", "assistant": "YOUR PREVIOUS REPLY"}
    return "\n\n".join(f"[{labels[m['role']]}]\n{m['content']}" for m in messages) + \
        "\n\n[USER]\nReply to the last USER message only."


def call_claude_code(messages: list[dict], cfg: dict) -> str:
    """Use the Claude Code CLI in headless mode, authenticated by CLAUDE_CODE_OAUTH_TOKEN
    (from `claude setup-token`), so usage counts against a Claude subscription, not API billing."""
    cmd = ["claude", "-p", "--model", cfg["model"], "--system-prompt", SYSTEM, "--tools", "",
           "--max-turns", "1", "--no-session-persistence", "--output-format", "text"]
    prompt = render_transcript(messages)
    delay = 30.0
    last = ""
    for attempt in range(1, 5):
        # Run in an empty directory so no repo files, CLAUDE.md or settings are picked up.
        with tempfile.TemporaryDirectory(prefix="aoc-claude-") as cwd:
            try:
                proc = subprocess.run(cmd, input=prompt, text=True, capture_output=True,
                                      cwd=cwd, timeout=900, env=os.environ.copy())
            except FileNotFoundError:
                raise SystemExit("the `claude` CLI is not installed (npm install -g @anthropic-ai/claude-code)") from None
            except subprocess.TimeoutExpired:
                last = "claude -p timed out"
                proc = None
        if proc is not None:
            if proc.returncode == 0 and proc.stdout.strip():
                return proc.stdout
            last = c.tail((proc.stderr or proc.stdout or f"exit {proc.returncode}"), 400)
            if re.search(r"(?i)(invalid|expired).*(token|credential)|not logged in|authentication", last):
                raise RuntimeError(f"Claude Code authentication failed; regenerate CLAUDE_CODE_OAUTH_TOKEN: {last}")
        if attempt < 4:
            c.log(f"claude -p failed ({last[:120]!r}); retrying in {delay:.0f}s (attempt {attempt})")
            time.sleep(delay + random.uniform(0, 5))
            delay *= 2
    raise RuntimeError(f"claude -p failed: {last}")


def call_anthropic_api(messages: list[dict], cfg: dict) -> str:
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        raise SystemExit("ANTHROPIC_API_KEY is not set")
    body = json.dumps({
        "model": cfg["model"], "max_tokens": cfg["max_output_tokens"],
        "system": SYSTEM, "messages": messages,
    }).encode()
    delay = 5.0
    for attempt in range(1, 7):
        req = urllib.request.Request(API_URL, data=body, method="POST", headers={
            "x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=600) as resp:
                data = json.load(resp)
            return "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:300]
            if exc.code in (408, 409, 429, 500, 502, 503, 504, 529) and attempt < 6:
                wait = float(exc.headers.get("retry-after") or delay) + random.uniform(0, 2)
                c.log(f"API HTTP {exc.code}; retrying in {wait:.0f}s (attempt {attempt})")
                time.sleep(wait)
                delay = min(delay * 2, 90)
                continue
            raise RuntimeError(f"Anthropic API error {exc.code}: {detail}") from None
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            if attempt < 6:
                time.sleep(delay)
                delay = min(delay * 2, 90)
                continue
            raise RuntimeError(f"Anthropic API unreachable: {exc}") from None
    raise RuntimeError("Anthropic API: retries exhausted")


_FENCE = re.compile(r"```[^\n]*\n(.*?)```", re.S)


def extract_code(reply: str) -> str:
    blocks = _FENCE.findall(reply)
    code = max(blocks, key=len) if blocks else reply
    return code.strip("\n") + "\n"


# ------------------------------------------------------------------ prompts

def task_prompt(year: int, day: int, lang: dict, toolchain: str, puzzle: str, parts: int) -> str:
    build = lang.get("build") or "none (interpreted or run directly)"
    availability = ("Both parts of the puzzle are available below. Print both answers."
                    if parts >= 2 else
                    "Only part 1 is published so far. Solve part 1 and print `-` as the second line.")
    return (f"Language: {lang['name']}\nToolchain on the runner: {toolchain}\n"
            f"Source file name: {lang['file']}\nBuild command: {build}\nRun command: {lang['run']}\n"
            f"Language notes: {lang.get('hint', '')}\n\n{availability}\n\n"
            f"Advent of Code {year}, day {day}\n\n{puzzle}")


def repair_prompt(lang: dict, info: dict, cfg: dict) -> str:
    v = info["verdict"]
    if v == "build_failed":
        what = f"The build failed. Build command: {lang.get('build')}\n\nBuild output:\n{info['error']}"
    elif v == "runtime_error":
        what = f"The program crashed or failed at runtime:\n{info['error']}"
    elif v == "timeout":
        what = (f"The program ran longer than {cfg['run_timeout_seconds']} seconds on the real puzzle input. "
                "It needs a substantially faster algorithm or data structure.")
    elif v == "bad_output":
        what = f"The program did not print the required answer lines to stdout:\n{info['error']}"
    else:
        parts = ", ".join(str(p) for p in info.get("wrong_parts", [])) or "one of the parts"
        what = (f"The program ran, but its answer for part {parts} was judged incorrect "
                f"(it printed {info.get('output')!r}). Re-read the puzzle statement carefully for details "
                "or edge cases you missed, and fix the logic. Do not hard-code any answer.")
    return (f"That attempt did not work.\n\n{what}\n\nReturn the complete corrected source file in one "
            "fenced code block and nothing else.")


# ------------------------------------------------------------------ commands

def _toolchains(langs: list[dict], include_missing: bool) -> dict[str, str]:
    found: dict[str, str] = {}
    for lang in langs:
        v = c.toolchain_version(lang)
        if v is None and not include_missing:
            c.log(f"skipping {lang['name']}: toolchain not installed on this runner")
            continue
        found[lang["id"]] = v or "not installed here (write for the latest stable release)"
    return found


def _save_source(year: int, day: int, lang: dict, code: str) -> None:
    path = c.source_path(year, day, lang)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(code, encoding="utf-8")


def _bump_state(year: int, day: int, lang_id: str) -> None:
    path = c.work_dir(year, day) / "state.json"
    state = c.read_json(path, {})
    state.setdefault("repairs", {})
    state["repairs"][lang_id] = state["repairs"].get(lang_id, 0) + 1
    c.write_json(path, state)


def cmd_generate(year: int, days: list[int], langs: list[dict], repair: bool, force: bool,
                 all_languages: bool) -> int:
    cfg = c.settings()
    if not days:
        c.log("generate: nothing to do (no days selected)")
        return 0
    toolchains = _toolchains(langs, include_missing=all_languages)
    jobs = []
    for day in days:
        wdir = c.work_dir(year, day)
        ddir = c.day_dir(year, day)
        puzzle = (wdir / "puzzle.md").read_text(encoding="utf-8") if (wdir / "puzzle.md").exists() else None
        if puzzle is None:
            c.log(f"day {day}: no puzzle text in {wdir}; run `fetch` first")
            continue
        meta = c.read_json(ddir / "meta.json", {})
        parts = max(1, int(meta.get("parts", 1) or 1))
        if repair:
            view = day_view(meta, c.read_json(ddir / "results.json", {"languages": {}}), langs)
            bad = failing_languages(view)
            todo = [(l, bad[l["id"]]) for l in langs if l["id"] in bad and l["id"] in toolchains]
        else:
            todo = [(l, None) for l in langs if l["id"] in toolchains
                    and (force or not c.source_path(year, day, l).exists()
                         or meta.get("parts_generated", 0) < parts)]
        for lang, info in todo:
            jobs.append((day, parts, puzzle, lang, info))

    if not jobs:
        c.log("generate: nothing needs generating")
        return 0
    c.log(f"generate: {len(jobs)} request(s) with model {cfg['model']}"
          + (" (repair round)" if repair else ""))

    def work(job):
        day, parts, puzzle, lang, info = job
        first = [{"role": "user", "content": task_prompt(year, day, lang, toolchains[lang["id"]], puzzle, parts)}]
        if info is None:
            messages = first
        else:
            prev = c.source_path(year, day, lang).read_text(encoding="utf-8")
            messages = first + [{"role": "assistant", "content": f"```\n{prev}```"},
                                {"role": "user", "content": repair_prompt(lang, info, cfg)}]
        code = extract_code(call_claude(messages, cfg))
        _save_source(year, day, lang, code)
        if info is not None:
            _bump_state(year, day, lang["id"])
        return day, lang["name"]

    errors = 0
    with ThreadPoolExecutor(max_workers=max(1, cfg["generate_concurrency"])) as pool:
        futures = {pool.submit(work, j): j for j in jobs}
        for fut in as_completed(futures):
            day, parts, _, lang, _ = futures[fut]
            try:
                fut.result()
                c.log(f"day {day}: wrote {lang['name']}")
            except Exception as exc:  # keep going; one failed request must not sink the run
                errors += 1
                c.log(f"day {day}: {lang['name']} failed: {exc}")

    if not repair:
        for day in {j[0] for j in jobs}:
            ddir = c.day_dir(year, day)
            meta = c.read_json(ddir / "meta.json", {})
            parts = max(j[1] for j in jobs if j[0] == day)
            meta.update(parts_generated=parts, model=cfg["model"], generated_at=c.now_iso())
            c.write_json(ddir / "meta.json", meta)
    return 1 if errors == len(jobs) else 0
