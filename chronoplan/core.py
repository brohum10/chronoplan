"""Map local recurrence labels to actual UTC instants without executing work."""

from datetime import UTC, datetime, time, timedelta
from functools import lru_cache
import hashlib
from importlib import resources
from zoneinfo import ZoneInfo

import tzdata

from .data import Schedule, ZONE, canonical, parse_date


@lru_cache(maxsize=64)
def load_zone(key):
    if type(key) is not str or len(key) > 100 or not ZONE.fullmatch(key):
        raise ValueError("invalid time zone key")
    # Load the packaged database explicitly, not the host's possibly different TZPATH.
    try:
        resource = resources.files("tzdata.zoneinfo").joinpath(*key.split("/"))
        with resource.open("rb") as stream:
            return ZoneInfo.from_file(stream, key=key)
    except (OSError, ValueError) as exc:
        raise ValueError(f"unknown or unsupported IANA zone: {key}") from exc


def candidates(wall, zone):
    """UTC-first roundtrip validation distinguishes 0, 1, and 2 valid instants."""
    if type(wall) is not datetime or wall.tzinfo is not None or wall.second or wall.microsecond:
        raise ValueError("wall time must be a naive minute-resolution datetime")
    found = set()
    for fold in (0, 1):
        instant = wall.replace(tzinfo=zone, fold=fold).astimezone(UTC)
        back = instant.astimezone(zone).replace(tzinfo=None)
        if back == wall:
            found.add(instant)
    # Never compare two same-zone local datetimes to distinguish a fold.
    return tuple(sorted(found))


def utc_text(instant):
    return instant.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def plan(schedule: Schedule, *, max_probes=2_000_000):
    if type(max_probes) is not int or not 1 <= max_probes <= 2_000_000:
        raise ValueError("max_probes must be integer 1-2000000")
    document = schedule.document()
    start, end = parse_date(document["start_date"]), parse_date(document["end_date"])
    cache, runs, skipped = {}, {}, []
    nominal_count, shifted, folds, emitted = 0, 0, 0, 0

    def lookup(wall, zone):
        key = (zone.key, wall)
        if key not in cache:
            if len(cache) >= max_probes:
                raise ValueError("wall-time probe budget exhausted; no partial plan is emitted")
            cache[key] = candidates(wall, zone)
        return cache[key]

    for job in document["jobs"]:
        zone = load_zone(job["zone"])
        day = start
        while day < end:
            if day.weekday() in job["weekdays"]:
                for clock in job["times"]:
                    wall = datetime.combine(day, time.fromisoformat(clock))
                    nominal_count += 1
                    resolved, minutes = wall, 0
                    instants = lookup(wall, zone)
                    if not instants:
                        if job["gap"] == "skip":
                            skipped.append(
                                dict(
                                    job=job["id"],
                                    zone=job["zone"],
                                    nominal_wall=wall.isoformat(timespec="minutes"),
                                    reason="nonexistent_local_time",
                                )
                            )
                            continue
                        # At most 24 hours of minute-grid lookahead, including skipped dates.
                        for minutes in range(1, 1441):
                            resolved = wall + timedelta(minutes=minutes)
                            instants = lookup(resolved, zone)
                            if instants:
                                break
                        else:
                            raise ValueError("gap has no valid minute within the 24-hour lookahead")
                        shifted += 1
                    if len(instants) == 2:
                        folds += 1
                        if job["fold"] == "first":
                            instants = instants[:1]
                        elif job["fold"] == "second":
                            instants = instants[1:]
                    for instant in instants:
                        emitted += 1
                        local = instant.astimezone(zone)
                        origin = dict(
                            nominal_wall=wall.isoformat(timespec="minutes"),
                            resolved_wall=resolved.isoformat(timespec="minutes"),
                            resolution=(
                                "gap_next_valid"
                                if minutes
                                else "fold" if len(lookup(resolved, zone)) == 2 else "normal"
                            ),
                            shift_minutes=minutes,
                            fold=local.fold,
                        )
                        key = (job["id"], instant)
                        if key not in runs:
                            identifier = hashlib.sha256(
                                canonical(
                                    dict(
                                        version=1,
                                        job=job["id"],
                                        zone=job["zone"],
                                        utc=utc_text(instant),
                                    )
                                ).encode()
                            ).hexdigest()
                            runs[key] = dict(
                                id=identifier,
                                job=job["id"],
                                zone=job["zone"],
                                utc=utc_text(instant),
                                local=local.isoformat(timespec="minutes"),
                                origins=[],
                            )
                        runs[key]["origins"].append(origin)
            day += timedelta(days=1)
    result = sorted(runs.values(), key=lambda row: (row["utc"], row["job"]))
    for row in result:
        row["origins"].sort(key=lambda origin: origin["nominal_wall"])
    return dict(
        version=1,
        schedule_sha256=schedule.sha256,
        timezone_data=dict(
            package=tzdata.__version__, iana=tzdata.IANA_VERSION, source="packaged tzdata"
        ),
        range=dict(
            start_date=document["start_date"],
            end_date_exclusive=document["end_date"],
            basis="each job's local dates",
        ),
        stats=dict(
            nominal_occurrences=nominal_count,
            shifted_nominals=shifted,
            ambiguous_nominals=folds,
            skipped_nominals=len(skipped),
            unique_runs=len(result),
            coalesced_occurrences=emitted - len(result),
            unique_wall_time_probes=len(cache),
        ),
        runs=result,
        skipped=skipped,
    )
