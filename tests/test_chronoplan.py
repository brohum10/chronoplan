import copy
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import tzdata

from chronoplan import Schedule, candidates, load_zone, plan
from chronoplan.data import MAX_BYTES, strict_json

ROOT = Path(__file__).resolve().parents[1]


def document(
    start="2026-11-01",
    end="2026-11-02",
    zone="America/New_York",
    times=None,
    gap="skip",
    fold="both",
):
    return dict(
        version=1,
        start_date=start,
        end_date=end,
        jobs=[
            dict(
                id="job",
                zone=zone,
                times=times or ["01:30"],
                weekdays=list(range(7)),
                gap=gap,
                fold=fold,
            )
        ],
    )


def fixture(name):
    return Schedule.load(ROOT / "examples" / f"{name}.json")


class DataTests(unittest.TestCase):
    def test_detached_input_and_output(self):
        doc = document()
        schedule = Schedule.from_document(doc)
        doc["jobs"][0]["times"] = ["00:00"]
        schedule.document()["jobs"].clear()
        self.assertEqual(schedule.document()["jobs"][0]["times"], ["01:30"])

    def test_input_order_does_not_change_hash_or_report(self):
        doc = document(times=["09:00", "01:30"])
        other = copy.deepcopy(doc["jobs"][0])
        other["id"] = "other"
        doc["jobs"].append(other)
        before = Schedule.from_document(doc)
        doc["jobs"].reverse()
        for job in doc["jobs"]:
            job["times"].reverse()
            job["weekdays"].reverse()
        after = Schedule.from_document(doc)
        self.assertEqual(before.sha256, after.sha256)
        self.assertEqual(plan(before), plan(after))

    def test_version_requires_integer_one(self):
        for value in (True, 1.0, 2, "1", None):
            doc = document()
            doc["version"] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                Schedule.from_document(doc)

    def test_unknown_fields_rejected(self):
        doc = document()
        doc["extra"] = 1
        with self.assertRaises(ValueError):
            Schedule.from_document(doc)
        doc.pop("extra")
        doc["jobs"][0]["extra"] = 1
        with self.assertRaises(ValueError):
            Schedule.from_document(doc)

    def test_policies_must_be_explicit(self):
        for field in ("gap", "fold"):
            doc = document()
            doc["jobs"][0].pop(field)
            with self.subTest(field=field), self.assertRaises(ValueError):
                Schedule.from_document(doc)

    def test_invalid_policy_values(self):
        for field, value in (
            ("gap", "shift_by_hour"),
            ("fold", "guess"),
            ("gap", True),
            ("fold", []),
        ):
            doc = document()
            doc["jobs"][0][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                Schedule.from_document(doc)

    def test_date_format_bounds_and_window(self):
        for start, end in (
            ("2026-1-01", "2026-01-02"),
            ("2026-02-30", "2026-03-01"),
            ("2026-01-01", "2026-01-01"),
            ("2026-01-02", "2026-01-01"),
            ("1999-12-31", "2000-01-01"),
            ("2101-01-01", "2101-01-02"),
            ("2026-01-01", "2027-01-03"),
        ):
            with self.subTest(start=start, end=end), self.assertRaises(ValueError):
                Schedule.from_document(document(start=start, end=end))

    def test_wall_clock_format_and_duplicates(self):
        for values in (
            ["24:00"],
            ["01:60"],
            ["1:30"],
            ["01:30:00"],
            [True],
            ["01:30", "01:30"],
            [],
            ["00:00"] * 13,
        ):
            doc = document()
            doc["jobs"][0]["times"] = values
            with self.subTest(values=values), self.assertRaises(ValueError):
                Schedule.from_document(doc)

    def test_weekday_validation(self):
        for values in ([True], [7], [-1], [0, 0], [], "Monday"):
            doc = document()
            doc["jobs"][0]["weekdays"] = values
            with self.subTest(values=values), self.assertRaises(ValueError):
                Schedule.from_document(doc)

    def test_job_and_nominal_limits(self):
        doc = document(start="2026-01-01", end="2027-01-01")
        doc["jobs"] = [dict(doc["jobs"][0], id=str(i)) for i in range(21)]
        with self.assertRaises(ValueError):
            Schedule.from_document(doc)
        doc["jobs"] = doc["jobs"][:20]
        for job in doc["jobs"]:
            job["times"] = ["00:00", "12:00"]
        with self.assertRaises(ValueError):
            Schedule.from_document(doc)

    def test_duplicate_and_invalid_job_ids(self):
        doc = document()
        doc["jobs"] *= 2
        with self.assertRaises(ValueError):
            Schedule.from_document(doc)
        doc = document()
        doc["jobs"][0]["id"] = "invalid id"
        with self.assertRaises(ValueError):
            Schedule.from_document(doc)

    def test_json_keys_numbers_bytes_and_encoding(self):
        for text in ('{"x":1,"x":2}', '{"x":NaN}', '{"x":Infinity}'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                strict_json(text)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.json"
            for data in (b" " * (MAX_BYTES + 1), b"\xff"):
                path.write_bytes(data)
                with self.assertRaises(ValueError):
                    Schedule.load(path)


class ResolutionTests(unittest.TestCase):
    def test_normal_and_fractional_offset(self):
        result = candidates(datetime(2026, 1, 1, 9), load_zone("Asia/Kathmandu"))
        self.assertEqual(result, (datetime(2026, 1, 1, 3, 15, tzinfo=UTC),))

    def test_missing_new_york_time_has_no_candidates(self):
        self.assertEqual(candidates(datetime(2026, 3, 8, 2, 30), load_zone("America/New_York")), ())

    def test_new_york_fold_has_two_distinct_utc_instants(self):
        result = candidates(datetime(2026, 11, 1, 1, 30), load_zone("America/New_York"))
        self.assertEqual(
            result,
            (datetime(2026, 11, 1, 5, 30, tzinfo=UTC), datetime(2026, 11, 1, 6, 30, tzinfo=UTC)),
        )

    def test_lord_howe_fold_is_half_an_hour(self):
        result = candidates(datetime(2026, 4, 5, 1, 45), load_zone("Australia/Lord_Howe"))
        self.assertEqual(result[1] - result[0], timedelta(minutes=30))

    def test_lord_howe_gap_is_not_assumed_to_be_one_hour(self):
        report = plan(
            Schedule.from_document(
                document(
                    start="2026-10-04",
                    end="2026-10-05",
                    zone="Australia/Lord_Howe",
                    times=["02:15"],
                    gap="next_valid",
                )
            )
        )
        self.assertEqual(report["runs"][0]["origins"][0]["shift_minutes"], 15)
        self.assertIn("02:30", report["runs"][0]["local"])

    def test_samoa_entire_missing_date(self):
        self.assertEqual(candidates(datetime(2011, 12, 30, 12), load_zone("Pacific/Apia")), ())
        report = plan(fixture("samoa-skipped-date"))
        self.assertEqual(report["stats"]["shifted_nominals"], 1)
        self.assertEqual(report["stats"]["coalesced_occurrences"], 1)
        self.assertEqual(report["runs"][0]["origins"][0]["shift_minutes"], 1440)

    def test_unknown_and_unsafe_zone_keys(self):
        for key in (
            "Not/AZone",
            "../UTC",
            "/etc/passwd",
            "America\\New_York",
            "Etc",
            "x" * 101,
            "europe/london",
            "america/New_York",
            "utc",
        ):
            with self.subTest(key=key), self.assertRaises(ValueError):
                load_zone(key)

    def test_wall_datetime_contract(self):
        for wall in (
            datetime(2026, 1, 1, tzinfo=UTC),
            datetime(2026, 1, 1, 1, 2, 3),
            datetime(2026, 1, 1, microsecond=1),
        ):
            with self.subTest(wall=wall), self.assertRaises(ValueError):
                candidates(wall, load_zone("UTC"))

    def test_8640_wall_minutes_against_independent_utc_enumeration(self):
        # No assigning fold to local labels: enumerate UTC forward and group observed wall labels.
        cases = [
            ("America/New_York", datetime(2026, 3, 8)),
            ("America/New_York", datetime(2026, 11, 1)),
            ("Europe/London", datetime(2026, 10, 25)),
            ("Australia/Lord_Howe", datetime(2026, 4, 5)),
            ("Australia/Lord_Howe", datetime(2026, 10, 4)),
            ("Pacific/Apia", datetime(2011, 12, 30)),
        ]
        checked = 0
        for key, day in cases:
            zone = load_zone(key)
            oracle = {}
            beginning = (day - timedelta(days=1)).replace(tzinfo=UTC)
            for minute in range(3 * 24 * 60):
                instant = beginning + timedelta(minutes=minute)
                wall = instant.astimezone(zone).replace(tzinfo=None)
                oracle.setdefault(wall, []).append(instant)
            for minute in range(24 * 60):
                wall = day + timedelta(minutes=minute)
                with self.subTest(zone=key, wall=wall):
                    self.assertEqual(candidates(wall, zone), tuple(oracle.get(wall, [])))
                checked += 1
        self.assertEqual(checked, 8640)

    def test_packaged_database_is_recorded(self):
        report = plan(fixture("europe-fold"))
        self.assertEqual(
            report["timezone_data"],
            dict(package=tzdata.__version__, iana=tzdata.IANA_VERSION, source="packaged tzdata"),
        )
        self.assertEqual(tzdata.__version__, "2026.5")


class PlanningTests(unittest.TestCase):
    def test_first_second_and_both_policies(self):
        first = plan(Schedule.from_document(document(fold="first")))["runs"]
        second = plan(Schedule.from_document(document(fold="second")))["runs"]
        both = plan(Schedule.from_document(document(fold="both")))["runs"]
        self.assertEqual(first[0]["utc"], "2026-11-01T05:30:00Z")
        self.assertEqual(second[0]["utc"], "2026-11-01T06:30:00Z")
        self.assertEqual([row["utc"] for row in both], [first[0]["utc"], second[0]["utc"]])
        self.assertEqual([row["origins"][0]["fold"] for row in both], [0, 1])

    def test_skip_policy_records_missing_label(self):
        report = plan(
            Schedule.from_document(document(start="2026-03-08", end="2026-03-09", times=["02:30"]))
        )
        self.assertEqual(report["runs"], [])
        self.assertEqual(report["stats"]["skipped_nominals"], 1)
        self.assertEqual(report["skipped"][0]["nominal_wall"], "2026-03-08T02:30")

    def test_gap_policy_chooses_first_valid_minute_not_same_minutes_next_hour(self):
        report = plan(
            Schedule.from_document(
                document(start="2026-03-08", end="2026-03-09", times=["02:30"], gap="next_valid")
            )
        )
        self.assertEqual(report["runs"][0]["local"], "2026-03-08T03:00-04:00")
        self.assertEqual(report["runs"][0]["origins"][0]["shift_minutes"], 30)

    def test_gap_collision_merges_origins_not_jobs(self):
        report = plan(fixture("us-gap-collision"))
        self.assertEqual(report["stats"]["unique_runs"], 1)
        self.assertEqual(report["stats"]["coalesced_occurrences"], 1)
        self.assertEqual(len(report["runs"][0]["origins"]), 2)

    def test_different_jobs_at_same_instant_are_not_merged(self):
        doc = document(zone="UTC", times=["12:00"])
        doc["jobs"].append(dict(doc["jobs"][0], id="other"))
        report = plan(Schedule.from_document(doc))
        self.assertEqual(report["stats"]["unique_runs"], 2)
        self.assertNotEqual(report["runs"][0]["id"], report["runs"][1]["id"])

    def test_weekdays_and_exclusive_local_end(self):
        doc = document(start="2026-10-23", end="2026-10-27", zone="UTC", times=["09:00"])
        doc["jobs"][0]["weekdays"] = [0, 4]
        result = plan(Schedule.from_document(doc))
        self.assertEqual(
            [row["utc"] for row in result["runs"]], ["2026-10-23T09:00:00Z", "2026-10-26T09:00:00Z"]
        )

    def test_wall_daily_is_not_fixed_24_hour_utc_interval(self):
        result = plan(
            Schedule.from_document(document(start="2026-03-07", end="2026-03-10", times=["09:00"]))
        )
        instants = [datetime.fromisoformat(row["utc"]) for row in result["runs"]]
        self.assertEqual(instants[1] - instants[0], timedelta(hours=23))
        self.assertEqual(instants[2] - instants[1], timedelta(hours=24))

    def test_fall_daily_can_have_25_hour_utc_interval(self):
        result = plan(
            Schedule.from_document(document(start="2026-10-31", end="2026-11-03", times=["09:00"]))
        )
        instants = [datetime.fromisoformat(row["utc"]) for row in result["runs"]]
        self.assertEqual(instants[1] - instants[0], timedelta(hours=25))

    def test_leap_day_is_preserved(self):
        result = plan(
            Schedule.from_document(document(start="2028-02-28", end="2028-03-01", zone="UTC"))
        )
        self.assertEqual(len(result["runs"]), 2)
        self.assertIn("2028-02-29", result["runs"][1]["local"])

    def test_run_ids_do_not_depend_on_report_window(self):
        short = plan(Schedule.from_document(document(fold="first")))["runs"][0]
        long = plan(
            Schedule.from_document(document(start="2026-10-31", end="2026-11-03", fold="first"))
        )["runs"]
        same = next(row for row in long if row["utc"] == short["utc"])
        self.assertEqual(same["id"], short["id"])

    def test_gap_shift_can_cross_end_of_nominal_date_range(self):
        result = plan(
            Schedule.from_document(
                document(
                    start="2011-12-30",
                    end="2011-12-31",
                    zone="Pacific/Apia",
                    times=["00:00"],
                    gap="next_valid",
                )
            )
        )
        self.assertIn("2011-12-31T00:00", result["runs"][0]["local"])

    def test_probe_budget_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "budget exhausted"):
            plan(fixture("europe-fold"), max_probes=1)

    def test_invalid_probe_limits(self):
        for value in (0, -1, True, 1.5, 2_000_001):
            with self.subTest(value=value), self.assertRaises(ValueError):
                plan(fixture("europe-fold"), max_probes=value)

    def test_gap_lookahead_has_a_bound(self):
        schedule = Schedule.from_document(document(times=["00:00"], gap="next_valid"))
        with patch("chronoplan.core.candidates", return_value=()):
            with self.assertRaisesRegex(ValueError, "24-hour lookahead"):
                plan(schedule)


class CliTests(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run(
            [sys.executable, "-m", "chronoplan", *map(str, args)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=15,
        )

    def test_json_and_text_output(self):
        result = self.run_cli(ROOT / "examples/europe-fold.json")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["stats"]["unique_runs"], 4)
        result = self.run_cli(ROOT / "examples/europe-fold.json", "--format", "text")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("2026-10-25T01:30:00Z", result.stdout)

    def test_invalid_file_and_budget_emit_no_partial_json(self):
        for args in (
            (ROOT / "missing.json",),
            (ROOT / "examples/europe-fold.json", "--max-probes", "1"),
        ):
            result = self.run_cli(*args)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(result.stdout, "")
            self.assertIn("error:", result.stderr)

    def test_unknown_zone_after_valid_job_emits_no_partial_plan(self):
        doc = document(zone="UTC")
        doc["jobs"].append(dict(doc["jobs"][0], id="zzz", zone="Unknown/Zone"))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.json"
            path.write_text(json.dumps(doc), encoding="utf-8")
            result = self.run_cli(path)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(result.stdout, "")


if __name__ == "__main__":
    unittest.main()
