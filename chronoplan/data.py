"""Strict recurrence specifications: explicit local-time gap and fold policies."""

from dataclasses import dataclass
from datetime import date, timedelta
import hashlib
import json
from pathlib import Path
import re

MAX_BYTES = 200_000
MAX_NOMINALS = 10_000
NAME = re.compile(r"[A-Za-z0-9_.:-]{1,100}\Z")
ZONE = re.compile(r"[A-Za-z0-9_+-]+(?:/[A-Za-z0-9_+-]+)*\Z")
DAY = re.compile(r"\d{4}-\d{2}-\d{2}\Z", re.ASCII)
TIME = re.compile(r"(?:[01]\d|2[0-3]):[0-5]\d\Z", re.ASCII)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def strict_json(text):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON field")
            result[key] = value
        return result

    def constant(_):
        raise ValueError("non-finite JSON constant")

    return json.loads(text, object_pairs_hook=pairs, parse_constant=constant)


def parse_date(value):
    if type(value) is not str or not DAY.fullmatch(value):
        raise ValueError("dates must use YYYY-MM-DD")
    return date.fromisoformat(value)


@dataclass(frozen=True)
class Schedule:
    encoded: str

    @classmethod
    def from_document(cls, document):
        if type(document) is not dict or set(document) != {
            "version",
            "start_date",
            "end_date",
            "jobs",
        }:
            raise ValueError("schedule needs exactly version/start_date/end_date/jobs")
        if type(document["version"]) is not int or document["version"] != 1:
            raise ValueError("version must be integer 1")
        start, end = parse_date(document["start_date"]), parse_date(document["end_date"])
        if not date(2000, 1, 1) <= start < end <= date(2101, 1, 1) or (end - start).days > 366:
            raise ValueError("use a nonempty range of at most 366 local dates within 2000-2100")
        jobs = document["jobs"]
        if type(jobs) is not list or not 1 <= len(jobs) <= 20:
            raise ValueError("need 1-20 jobs")
        ids, normalized, nominal_count = set(), [], 0
        for job in jobs:
            if type(job) is not dict or set(job) != {
                "id",
                "zone",
                "times",
                "weekdays",
                "gap",
                "fold",
            }:
                raise ValueError("each job needs exactly id/zone/times/weekdays/gap/fold")
            if type(job["id"]) is not str or not NAME.fullmatch(job["id"]) or job["id"] in ids:
                raise ValueError("job IDs must be valid and unique")
            ids.add(job["id"])
            if (
                type(job["zone"]) is not str
                or len(job["zone"]) > 100
                or not ZONE.fullmatch(job["zone"])
            ):
                raise ValueError("zone must be a bounded IANA key, not a filesystem path")
            times = job["times"]
            if (
                type(times) is not list
                or not 1 <= len(times) <= 12
                or any(type(item) is not str or not TIME.fullmatch(item) for item in times)
                or len(set(times)) != len(times)
            ):
                raise ValueError("need 1-12 distinct HH:MM wall times")
            weekdays = job["weekdays"]
            if (
                type(weekdays) is not list
                or not 1 <= len(weekdays) <= 7
                or any(type(item) is not int or not 0 <= item <= 6 for item in weekdays)
                or len(set(weekdays)) != len(weekdays)
            ):
                raise ValueError("weekdays are distinct integers 0=Monday through 6=Sunday")
            if type(job["gap"]) is not str or job["gap"] not in {"skip", "next_valid"}:
                raise ValueError("gap policy must be skip or next_valid")
            if type(job["fold"]) is not str or job["fold"] not in {"first", "second", "both"}:
                raise ValueError("fold policy must be first, second, or both")
            nominal_count += len(times) * sum(
                (start + timedelta(days=i)).weekday() in weekdays for i in range((end - start).days)
            )
            normalized.append(
                dict(
                    id=job["id"],
                    zone=job["zone"],
                    times=sorted(times),
                    weekdays=sorted(weekdays),
                    gap=job["gap"],
                    fold=job["fold"],
                )
            )
        if nominal_count > MAX_NOMINALS:
            raise ValueError("schedule exceeds 10000 nominal occurrences")
        encoded = canonical(
            dict(
                version=1,
                start_date=start.isoformat(),
                end_date=end.isoformat(),
                jobs=sorted(normalized, key=lambda job: job["id"]),
            )
        )
        if len(encoded.encode()) > MAX_BYTES:
            raise ValueError("normalized input exceeds byte limit")
        return cls(encoded)

    @classmethod
    def load(cls, path):
        with Path(path).open("rb") as source:
            data = source.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise ValueError("input exceeds 200000 bytes")
        return cls.from_document(strict_json(data.decode("utf-8")))

    def document(self):
        return json.loads(self.encoded)

    @property
    def sha256(self):
        return hashlib.sha256(self.encoded.encode()).hexdigest()
