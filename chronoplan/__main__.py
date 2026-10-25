import argparse
import json
from pathlib import Path
import sys

from . import Schedule, plan


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Preview local recurring jobs across time-zone transitions; never execute them."
    )
    parser.add_argument("schedule", type=Path)
    parser.add_argument("--format", choices=["json", "text"], default="json")
    parser.add_argument("--max-probes", type=int, default=2_000_000)
    args = parser.parse_args(argv)
    try:
        report = plan(Schedule.load(args.schedule), max_probes=args.max_probes)
        if args.format == "json":
            print(json.dumps(report, indent=2, sort_keys=True))
        else:
            print(
                f'ChronoPlan: {report["stats"]["unique_runs"]} runs; {report["stats"]["skipped_nominals"]} skipped; '
                f'{report["stats"]["coalesced_occurrences"]} coalesced'
            )
            print(
                f'Time-zone data: tzdata {report["timezone_data"]["package"]} / IANA {report["timezone_data"]["iana"]}'
            )
            for row in report["runs"]:
                print(f'{row["utc"]} | {row["job"]} | {row["local"]} [{row["zone"]}]')
                for origin in row["origins"]:
                    print(
                        f'  {origin["nominal_wall"]}: {origin["resolution"]}; shift={origin["shift_minutes"]}m; fold={origin["fold"]}'
                    )
            for row in report["skipped"]:
                print(f'SKIP {row["job"]}: {row["nominal_wall"]} [{row["zone"]}]')
        return 0
    except (OSError, ValueError, OverflowError, RecursionError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
