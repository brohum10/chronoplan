"""Reproduce complete schedule reports using the pinned packaged IANA database."""

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from chronoplan import Schedule, plan


def reproduce():
    return {
        path.stem: plan(Schedule.load(path)) for path in sorted((ROOT / "examples").glob("*.json"))
    }


def main():
    actual = reproduce()
    expected = json.loads((ROOT / "evidence/reference.json").read_text(encoding="utf-8"))
    if actual != expected:
        raise SystemExit(
            "Reference mismatch: inspect policy or time-zone-data changes before updating evidence."
        )
    for name, report in actual.items():
        stats = report["stats"]
        print(
            f'{name}: {stats["unique_runs"]} runs, {stats["skipped_nominals"]} skipped, '
            f'{stats["coalesced_occurrences"]} coalesced'
        )
    print(
        "Verified every UTC instant, origin, stable ID, policy outcome, and time-zone-data version."
    )


if __name__ == "__main__":
    main()
