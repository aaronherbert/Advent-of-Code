"""Paths, configuration and small helpers shared by every command."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(os.environ.get("AOC_ROOT") or Path(__file__).resolve().parent.parent)
HARNESS_DIR = Path(__file__).resolve().parent

# Environment variable names (or fragments) that must never reach generated code.
_SECRET_FRAGMENTS = ("TOKEN", "SECRET", "KEY", "PASSWORD", "COOKIE", "SESSION", "CREDENTIAL", "AUTH")
_SECRET_EXACT = {"AOC_SESSION", "ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN", "GITHUB_TOKEN", "ACTIONS_RUNTIME_TOKEN",
                 "ACTIONS_ID_TOKEN_REQUEST_TOKEN", "ACTIONS_ID_TOKEN_REQUEST_URL"}


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


# ---------------------------------------------------------------- config

def settings() -> dict:
    data = read_json(ROOT / "config" / "settings.json", {})
    data = {k: v for k, v in data.items() if not k.startswith("_")}
    for key, default in list(data.items()):
        env = os.environ.get("AOC_" + key.upper())
        if env is None or env == "":
            continue
        try:
            if isinstance(default, bool):
                data[key] = env.lower() in ("1", "true", "yes")
            elif isinstance(default, int):
                data[key] = int(env)
            elif isinstance(default, float):
                data[key] = float(env)
            else:
                data[key] = env
        except ValueError:
            log(f"warning: ignoring invalid AOC_{key.upper()}={env!r}")
    return data


def languages(include_disabled: bool = False) -> list[dict]:
    raw = read_json(ROOT / "config" / "languages.json", {"languages": []})["languages"]
    only = os.environ.get("AOC_LANGS")
    wanted = {x.strip() for x in only.split(",")} if only else None
    out = []
    for lang in raw:
        if not include_disabled and not lang.get("enabled", True):
            continue
        if wanted is not None and lang["id"] not in wanted:
            continue
        out.append(lang)
    return out


def select_languages(spec: str | None, include_disabled: bool = False) -> list[dict]:
    langs = languages(include_disabled)
    if not spec:
        return langs
    wanted = [x.strip() for x in spec.split(",") if x.strip()]
    known = {l["id"] for l in langs}
    missing = [w for w in wanted if w not in known]
    if missing:
        raise SystemExit(f"unknown or disabled language(s): {', '.join(missing)}")
    return [l for l in langs if l["id"] in wanted]


# ---------------------------------------------------------------- paths

def day_dir(year: int, day: int) -> Path:
    return ROOT / str(year) / f"day{day:02d}"


def work_dir(year: int, day: int) -> Path:
    return ROOT / ".work" / str(year) / f"day{day:02d}"


def build_dir(year: int, day: int, lang_id: str) -> Path:
    return ROOT / ".build" / str(year) / f"day{day:02d}" / lang_id


def source_path(year: int, day: int, lang: dict) -> Path:
    return day_dir(year, day) / lang["id"] / lang["file"]


def all_years() -> list[int]:
    return sorted(int(p.name) for p in ROOT.iterdir() if p.is_dir() and re.fullmatch(r"\d{4}", p.name))


def days_with_data(year: int) -> list[int]:
    base = ROOT / str(year)
    if not base.is_dir():
        return []
    return sorted(int(p.name[3:]) for p in base.iterdir() if p.is_dir() and re.fullmatch(r"day\d{2}", p.name))


# ---------------------------------------------------------------- json / files

def read_json(path: Path, default=None):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return default


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, sort_keys=True, ensure_ascii=False)
        fh.write("\n")
    os.replace(tmp, path)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def tail(text: str, limit: int = 1500) -> str:
    text = text.strip()
    return text if len(text) <= limit else "…" + text[-limit:]


# ---------------------------------------------------------------- days & calendar

def parse_days(spec: str | None, year: int) -> list[int]:
    """'1-5,8' -> [1,2,3,4,5,8]; 'all' -> every day up to the unlocked one; 'auto'/None -> plan.json."""
    if spec in (None, "", "auto"):
        plan = read_json(ROOT / ".work" / "plan.json")
        if not plan or plan.get("year") != year:
            return []
        return [d["day"] for d in plan["days"]]
    if spec == "all":
        return days_with_data(year)
    days: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-", 1)
            days.update(range(int(a), int(b) + 1))
        elif part:
            days.add(int(part))
    bad = [d for d in days if not 1 <= d <= 25]
    if bad:
        raise SystemExit(f"day out of range 1-25: {bad}")
    return sorted(days)


def last_unlocked_day(year: int, now: dt.datetime | None = None) -> int:
    """Puzzles unlock at midnight US Eastern (UTC-5) on Dec 1..N."""
    cfg = settings()
    now = now or dt.datetime.now(dt.timezone.utc)
    local = now + dt.timedelta(hours=cfg.get("puzzle_unlock_utc_offset_hours", -5))
    max_day = cfg.get("max_day", 25)
    if local.year > year:
        return max_day
    if local.year < year or local.month < 12:
        return 0
    return min(max_day, local.day)


def default_year() -> int:
    local = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=-5)
    return local.year


# ---------------------------------------------------------------- subprocess helpers

def scrubbed_env(extra: dict | None = None) -> dict:
    """Copy of the environment without anything that looks like a credential."""
    env = {}
    for k, v in os.environ.items():
        ku = k.upper()
        if k in _SECRET_EXACT or ku.startswith("ACTIONS_") or ku.startswith("INPUT_"):
            continue
        if any(f in ku for f in _SECRET_FRAGMENTS):
            continue
        env[k] = v
    env.setdefault("LANG", "C.UTF-8")
    env["DOTNET_CLI_TELEMETRY_OPTOUT"] = "1"
    env["DOTNET_NOLOGO"] = "1"
    env["DOTNET_SKIP_FIRST_TIME_EXPERIENCE"] = "1"
    if extra:
        env.update(extra)
    return env


def run_capture(cmd: str | list[str], cwd: Path | None = None, timeout: int = 60,
                shell: bool = False, env: dict | None = None) -> tuple[int, str, bool]:
    """Run a command; return (exit_code, combined_output, timed_out)."""
    try:
        proc = subprocess.run(
            cmd, cwd=cwd, shell=shell, env=env or scrubbed_env(), timeout=timeout,
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            executable="/bin/bash" if shell else None, start_new_session=True,
        )
        return proc.returncode, proc.stdout.decode("utf-8", "replace"), False
    except subprocess.TimeoutExpired as exc:
        out = (exc.stdout or b"").decode("utf-8", "replace") if isinstance(exc.stdout, bytes) else ""
        return 124, out, True
    except FileNotFoundError as exc:
        return 127, str(exc), False


_TOOLCHAIN_CACHE: dict[str, str | None] = {}


def toolchain_version(lang: dict) -> str | None:
    """First line of the toolchain's version output, or None if it is not installed."""
    lid = lang["id"]
    if lid in _TOOLCHAIN_CACHE:
        return _TOOLCHAIN_CACHE[lid]
    code, out, _ = run_capture(lang["version"], timeout=60, shell=True)
    result = None
    if code == 0:
        lines = [l.strip() for l in out.splitlines()
                 if l.strip() and not l.startswith(("Picked up ", "WARNING", "Warning"))]
        result = lines[0][:120] if lines else "unknown"
    _TOOLCHAIN_CACHE[lid] = result
    return result


def copytree_clean(src: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
