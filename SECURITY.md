# Safety and trust boundaries

ChronoPlan parses local JSON and packaged time-zone data. It does not execute
job names as commands, contact services, modify calendars, set timers, or write
reports to disk. Shell redirection is outside the program and may overwrite
files; choose new report filenames. Job names and recurrence patterns can be
sensitive, so sanitize reports before sharing them publicly.

Zone keys are bounded and restricted to IANA-style components. Absolute paths,
traversal, backslashes, and arbitrary TZif uploads are unsupported. Zones are
loaded only from the installed first-party tzdata package. Dependency integrity
and the Python environment remain part of the trusted computing base.

The specification and probe limits bound algorithmic work but do not provide a
hard memory or wall-clock quota. The largest allowed cache may be expensive.
Use OS resource controls for untrusted workloads. Errors produce no partial
plan, but reports can intentionally contain zero runs when skip policies apply.

Plan IDs are content identifiers, not signatures or execution guarantees. The
same ID can be dispatched repeatedly by an external system. Time-zone rules
can change after a plan is generated, and shifts/coalescing may not match a
particular application's business semantics. Review policies and refresh data
before any real scheduling, billing, or safety-relevant integration.

Use GitHub's private vulnerability reporting when available. Never put secrets
or private scheduling information into public issues.
