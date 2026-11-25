# Advent of Code in every language

A harness that solves each [Advent of Code](https://adventofcode.com) puzzle in 25 programming languages,
runs every solution against your puzzle input, and publishes the answers and a performance comparison to
GitHub Pages.

Each day, a GitHub Action:

1. **fetches** the puzzle text and your personal input (private, never committed),
2. asks **Claude** to write a solution in every language,
3. **builds and times** all of them on the same input (median of several runs, peak memory, build time),
4. gives Claude two chances to **repair** anything that fails to build, crashes, times out or disagrees,
5. commits the code and results to `2026/dayNN/` and **publishes the site**.

Puzzle text and inputs stay out of the repo and out of the site, as Advent of Code asks. The site shows only
answers, timings and code. This repo never submits answers for you.

## One-time setup

1. Create the public repo and push this code to `main`.
2. **Settings → Pages → Build and deployment → Source: GitHub Actions.**
3. **Settings → Secrets and variables → Actions → Secrets:**
   - `AOC_SESSION`: the `session` cookie from adventofcode.com (browser dev tools → Application → Cookies).
     It expires after about a month, so refresh it if the fetch step starts failing.
   - `ANTHROPIC_API_KEY`: an API key used to write the solutions.
4. **Same page → Variables:**
   - `AOC_CONTACT` (recommended): your email or GitHub handle. It goes into the User-Agent so Advent of Code
     can reach you, as their automation guidelines request.
   - `AOC_MODEL` (optional): overrides `model` in `config/settings.json`.
5. **Actions → Advent of Code → Run workflow** to try it. Before December 1 there is nothing to fetch, so
   test with `year` set to a past year (for example `2025`) and `days` set to `1`.

After that it runs every two hours in December, starting at 00:23 US Eastern, just after puzzles unlock.

## Day to day

- Day N appears at midnight US Eastern. Within a couple of hours the workflow generates the **part 1**
  solutions, because part 2 is hidden until you solve part 1.
- Open the site, take the part 1 answer, and **submit it yourself** on adventofcode.com.
- Part 2 is now visible. The next scheduled run notices, regenerates every language for both parts and
  re-benchmarks. To skip the wait, run the workflow by hand with `days` = `N`.
- Once Advent of Code accepts an answer, the harness reads it back from the puzzle page. From then on it is
  the ground truth ("Accepted by adventofcode.com" on the site). Until then, the answer most languages agree
  on is used ("Most languages agree").

## How results are judged

- **Correct** means the program's answer matches the accepted answer, or the consensus answer if nothing has
  been accepted yet (at least two languages agree and no tie). **Wrong answer**, **Build failed**, **Crashed**
  and **Timed out** are reported as such and left out of the speed ranking.
- **Speed** is the median wall-clock time of the whole process, startup included, over 5 runs after a first
  run that is reported separately. The headline number is the geometric mean, across days, of each
  language's time divided by the fastest correct language that day. The geometric mean keeps one huge outlier
  from dominating.
- **Memory** is peak resident set size from the kernel's rusage for the process.
- GitHub's shared runners are noisy and have 2 cores. Compare languages within a day (they run back to back on
  the same machine), not absolute numbers between days.

## Layout

```
config/languages.json     the 25 languages: build + run commands, hints for the model, enable/disable
config/settings.json      model, runs per benchmark, timeouts, repair rounds
harness/                  the Python (standard library only) harness and the static site
.github/workflows/aoc.yml the daily pipeline
.github/workflows/ci.yml  offline tests for the harness
scripts/                  toolchain installer for the runner
tests/                    offline tests with real fixture programs
2026/dayNN/<lang>/        the solutions, plus meta.json and results.json for each day
```

Every program follows one contract: read the whole puzzle input from stdin, print two lines (the part 1
answer, then the part 2 answer, or `-` if part 2 is not published yet).

## Running locally

Requires Python 3.10+ and whichever language toolchains you want to test.

```sh
python3 -m harness doctor                       # which toolchains are installed
export AOC_SESSION=...  ANTHROPIC_API_KEY=...
python3 -m harness fetch --year 2026            # writes the plan, stores puzzle + input in .work/ (git-ignored)
python3 -m harness generate                     # Claude writes solutions for the planned days
python3 -m harness bench                        # build + time everything
python3 -m harness generate --repair && python3 -m harness bench --only-changed
python3 -m harness report --year 2026           # leaderboard in the terminal
python3 -m harness site --out dist              # then: python3 -m http.server -d dist
python3 -m unittest discover -s tests           # offline harness tests
```

Useful flags: `--days 3` or `--days 1-5`, `--langs python,rust`, `--force`. `AOC_LANGS=python,go` limits every
command to those languages. To work offline, put `puzzle.md` and `input.txt` in `.work/2026/dayNN/` by hand.

## Customising

- **Drop or add a language:** edit `config/languages.json` (`"enabled": false` to drop one). A new language needs
  an `id`, `file`, optional `build`, `run`, `version` command and a `hint` for the model. Add the toolchain to
  `aoc.yml` or `scripts/install-toolchains.sh`. If a toolchain is missing on the runner, the harness skips that
  language instead of failing.
- **Change the model, run count, timeouts:** `config/settings.json`.
- **Next year:** nothing to change. The workflow defaults to the current year and creates `2027/`.

## Security model

Generated code is untrusted, so the pipeline separates what can run it from what holds credentials:

- The `solve` job has read-only repo access and no persisted git token. `AOC_SESSION` is visible only to the
  `fetch` step and `ANTHROPIC_API_KEY` only to the `generate` steps. Neither of those steps runs generated code.
  The `bench` steps run the generated programs with no secrets in their environment, and the harness strips
  anything that looks like a credential from the child environment as a second layer.
- Only source files, `meta.json` and `results.json` cross to the `publish` job, which has write access and runs
  no generated code. Symlinks and oversized files are dropped.
- Generated programs are still LLM-written code running on a throwaway GitHub-hosted VM with network access.
  Fork pull requests never get your secrets.
- Repair prompts tell the model that an answer was judged wrong but never what the right answer is, so it cannot
  hard-code it. Puzzle input is never sent to the API.

## Cost and limits

- Expect roughly 50 to 100 API calls per puzzle day: about 25 for part 1, 25 again once part 2 appears, plus
  repairs. Costs depend on the model you set; watch your usage in the Anthropic console after the first days.
- A full day is 25 languages × (build + 6 runs) on a 2-core runner, usually well under an hour. The job times
  out at 4 hours.
- Haskell, Scala, Kotlin, Swift, Zig and Dart have the most toolchain moving parts. Check the "Toolchain report"
  step of the first run.
- Advent of Code asks that AI not be used to chase global leaderboard times and that automation never submit
  answers. This harness does neither, but keep it in mind if you start solving at unlock time yourself.
