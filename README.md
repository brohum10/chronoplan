# ChronoPlan

[![Checks](https://github.com/brohum10/chronoplan/actions/workflows/ci.yml/badge.svg)](https://github.com/brohum10/chronoplan/actions/workflows/ci.yml)

**01:30 can happen twice. 02:30 can disappear. Sometimes an entire date is skipped.**

ChronoPlan previews recurring jobs against real time-zone rules, with explicit
policies for missing and repeated local times. It emits UTC run times, local
offsets, stable run IDs, and an explanation of every skipped, shifted, repeated,
or merged occurrence. It never executes jobs or modifies a calendar.

Python 3.12+ · offline CLI · pinned IANA data · MIT

## The problem in one example

For `Europe/London` on 2026-10-25, the pinned database maps the same local label
to two different instants:

```text
Local label       Offset   Actual UTC instant
2026-10-25 01:30   +01:00   2026-10-25 00:30Z
2026-10-25 01:30   +00:00   2026-10-25 01:30Z

fold=first  -> first instant
fold=second -> second instant
fold=both   -> both instants, each with a distinct run ID
```

Conversely, New York's 2026-03-08 02:30 has no matching instant. With `skip`,
the report records it without scheduling a run. With `next_valid`, it resolves
to **03:00**, not 03:30: that policy chooses the first valid minute after the
gap, rather than adding a presumed one-hour offset.

## Try the examples

From a cloned repository, create an isolated environment and install the package.
On macOS/Linux:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/python -m chronoplan examples/europe-fold.json --format text
.venv/bin/python -m chronoplan examples/us-gap-collision.json --format text
```

On Windows:

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install .
.venv\Scripts\python.exe -m chronoplan examples/europe-fold.json --format text
```

Installation downloads build tooling and the small first-party `tzdata` package.
After installation, planning requires no account, API key, server, or network.
The installed `chronoplan` command is equivalent to `python -m chronoplan`.

Default output is JSON; use `--format text` for a readable timeline. To save a
report, redirect stdout to a **new** filename. The program itself does not write
files, but shell redirection can overwrite an existing file.

## Explicit policy contract

```json
{
  "version": 1,
  "start_date": "2026-10-24",
  "end_date": "2026-10-27",
  "jobs": [
    {
      "id": "london-report",
      "zone": "Europe/London",
      "times": ["01:30"],
      "weekdays": [0, 1, 2, 3, 4, 5, 6],
      "gap": "skip",
      "fold": "both"
    }
  ]
}
```

- `start_date` is inclusive and `end_date` exclusive, interpreted as **local
  dates separately for each job**. This is not a shared UTC filter window.
- `times` are distinct minute-resolution `HH:MM` wall labels. Weekdays are
  integers, Monday 0 through Sunday 6. Jobs are daily/weekly recurrences, not
  cron expressions or full iCalendar recurrence rules.
- `gap`: `skip` or `next_valid`. The latter scans forward on the local minute
  grid for at most 24 hours. It can move an occurrence to a different local date,
  including beyond the nominal date range. Weekday selection applies to the
  **original** date and is not reapplied after a shift.
- `fold`: `first`, `second`, or `both`, meaning earlier/later UTC instant for an
  ambiguous label. Ordinary times still emit one run regardless of fold policy.
- Policies are required; the tool never silently guesses your intended behavior.
- Zone keys are case-sensitive members of the packaged IANA catalog, even on
  case-insensitive filesystems. Use `Europe/London`, not `europe/london`.
- If multiple labels for **the same job** resolve to the same UTC instant, they
  are coalesced into one run with all original labels retained. Different jobs
  at the same instant are never merged. Review this coalescing policy before
  integrating it with a system where each nominal occurrence is separate work.

## Architecture

```text
validated local recurrence specification
  -> enumerate selected local dates and wall labels
  -> classify each label against packaged time-zone data
     0 UTC candidates: gap policy
     1 UTC candidate:  ordinary occurrence
     2 UTC candidates: fold policy
  -> coalesce same-job/UTC collisions, retain origins
  -> UTC-sorted plan + skipped labels + audit counters
```

For each local label, try both `fold` values, convert to UTC, then convert back
to local time. Only exact roundtrips are valid candidates. Deduplication and
ordering happen in UTC, avoiding same-zone datetime comparisons that can hide
the distinction between repeated local times. It makes no assumption that a
transition is one hour: the tests include Lord Howe's half-hour shift and
Apia's skipped 2011-12-30.

Run IDs hash the versioned `(job ID, declared zone, UTC instant)` identity.
They remain stable when the report window changes but are **not execution
receipts, locks, or an exactly-once guarantee**. Renaming a job or zone alias
changes its IDs. Keep a separate durable dispatch ledger in a real scheduler.

## Reproducibility and evidence

ChronoPlan deliberately reads `tzdata` **2026.5 / IANA 2026e** directly from the
installed package using `ZoneInfo.from_file`. It does not silently prefer the
host's system database, and it does not change global `TZPATH` settings. Every
report records its data source and versions alongside the normalized input hash.

Time-zone rules are political data and can change. Pinning makes these examples
reproducible, **not eternally correct predictions**. Before operational use,
review data updates, update the dependency pin deliberately, regenerate plans,
and inspect changed UTC instants. A saved plan is not a substitute for that review.

After installation, run these with your environment's Python:

```sh
python -m unittest discover -s tests -v
python scripts/verify_reference.py
```

| Checked-in scenario | Unique runs | Skipped labels | Coalesced occurrences |
| --- | ---: | ---: | ---: |
| London repeated hour across three dates | 4 | 0 | 0 |
| New York missing time + collision | 1 | 1 | 1 |
| Lord Howe half-hour repeated interval | 2 | 0 | 0 |
| Samoa skipped date + following midnight | 1 | 0 | 1 |

[evidence/reference.json](evidence/reference.json) contains the complete reports.
The verifier recomputes and compares every field, including UTC instants,
origin labels, offsets, stable IDs, counters, and data versions.

The **39 tests** include an independent UTC-forward enumeration oracle checking
**8,640 local minute labels across six transition cases**. This checks the
mapping algorithm against the same database through a different path; it does
not independently certify the accuracy of the IANA rules. Other tests cover
weekday/date boundaries, leap days, 23/25-hour UTC intervals for daily jobs,
gap/fold policies, collision handling, strict input validation, probe budgets,
and CLI failure behavior. CI runs Linux and Windows with Python 3.12 and 3.14.

## Limits and safety

Planning is bounded to 20 jobs, 12 times per job, 366 local dates, and 10,000
nominal occurrences per input. Nominal dates must be within 2000–2100 (the
exclusive end date may be 2101-01-01). Input is limited
to 200,000 bytes. The default and maximum budget is two million distinct
wall-time probes; `--max-probes` can lower it. If validation, zone loading,
lookahead, or budget checks fail, exit 2 emits an error on stderr and **no
partial plan on stdout**. Successful previews exit 0, even if policy skips runs.

The cache and complete report are held in memory. Input bounds and probe
budgets are not hard CPU/memory isolation. There is no running daemon, queue,
retry policy, crash recovery, misfire catch-up, holiday calendar, leap-second
support, or job execution. A local-time daily recurrence is intentionally
different from a fixed 24-hour UTC interval. This is a learning/diagnostic tool,
not a production scheduler. See [SECURITY.md](SECURITY.md).

References: [Python zoneinfo documentation](https://docs.python.org/3.14/library/zoneinfo.html)
and the first-party [tzdata 2026.5 release](https://pypi.org/project/tzdata/2026.5/).
Built as a learning and portfolio project with AI assistance.
