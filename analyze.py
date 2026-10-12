#!/usr/bin/env python3
"""log-analyzer: parse web server access logs and print an actionable report.

The tool understands the Apache/Nginx *combined* log format, which has nine
space-separated fields::

    remote_host ident user [timestamp] "request" status bytes "referer" "user_agent"

It streams the input (so it works on files larger than memory), aggregates the
parsed entries, and renders a report as text, JSON or Markdown.
"""

import argparse
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable, Iterator, Optional, Sequence

# ---------------------------------------------------------------------------
# The combined log format
# ---------------------------------------------------------------------------
# Reference: https://httpd.apache.org/docs/current/logs.html#combined
#
# A single line looks like this:
#
#   127.0.0.1 - frank [10/Oct/2000:13:55:36 -0700] "GET /apache_pb.gif HTTP/1.0" 200 2326 "http://www.example.com/start.html" "Mozilla/4.08 [en] (Win98; I ;Nav)"
#
# The fields are, in order:
#   1. remote host (IP or hostname)
#   2. identd identity  (almost always "-")
#   3. user id          (almost always "-")
#   4. timestamp, wrapped in square brackets
#   5. the request line, wrapped in double quotes
#   6. HTTP status code
#   7. response size in bytes ("-" when nothing was returned)
#   8. the Referer header, wrapped in double quotes
#   9. the User-Agent header, wrapped in double quotes
#
# We use a regex rather than ``str.split()`` because the request, referer and
# user-agent fields may themselves contain spaces (user-agents routinely do).
LOG_PATTERN = re.compile(
    r"^(?P<ip>\S+) "
    r"(?P<ident>\S+) "
    r"(?P<user>\S+) "
    r"\[(?P<timestamp>[^\]]+)\] "
    r'"(?P<request>[^"]*)" '
    r"(?P<status>\d{3}) "
    r"(?P<size>\S+) "
    r'"(?P<referer>[^"]*)" '
    r'"(?P<user_agent>[^"]*)"'
)

# The timestamp field, e.g. "10/Oct/2000:13:55:36 -0700".
TIMESTAMP_FORMAT = "%d/%b/%Y:%H:%M:%S %z"

# Substrings that indicate an error line in looser, non-combined log files.
ERROR_KEYWORDS = ("error", "exception", "traceback", "critical", "fatal", "failed")


@dataclass(frozen=True)
class LogEntry:
    """One successfully parsed log line."""

    ip: str
    timestamp: Optional[datetime]
    method: str
    path: str
    protocol: str
    status: int
    size: int
    user_agent: str


def parse_timestamp(raw: str) -> Optional[datetime]:
    """Parse the bracketed timestamp, returning ``None`` if it is malformed."""
    try:
        return datetime.strptime(raw, TIMESTAMP_FORMAT)
    except ValueError:
        return None


def parse_size(raw: str) -> int:
    """Parse the response size. The combined format uses ``-`` for no body."""
    if raw == "-":
        return 0
    try:
        return int(raw)
    except ValueError:
        return 0


def parse_request(request: str) -> tuple[str, str, str]:
    """Split a request line into ``(method, path, protocol)``.

    Missing pieces become empty strings, so a bare ``-`` or a request without a
    protocol still yields a usable tuple instead of raising.
    """
    parts = request.split(" ", 2)
    while len(parts) < 3:
        parts.append("")
    return parts[0], parts[1], parts[2]


def parse_line(line: str) -> Optional[LogEntry]:
    """Parse one log line into a :class:`LogEntry`, or ``None`` if it does not match."""
    match = LOG_PATTERN.match(line)
    if match is None:
        return None
    fields = match.groupdict()
    method, path, protocol = parse_request(fields["request"])
    return LogEntry(
        ip=fields["ip"],
        timestamp=parse_timestamp(fields["timestamp"]),
        method=method,
        path=path,
        protocol=protocol,
        status=int(fields["status"]),
        size=parse_size(fields["size"]),
        user_agent=fields["user_agent"],
    )


def resolve_paths(raw_paths: Sequence[str]) -> list[Path]:
    """Turn CLI arguments into a concrete list of files.

    A directory expands to every ``*.log`` file it contains (sorted). A missing
    path raises :class:`FileNotFoundError` with a friendly message.
    """
    resolved: list[Path] = []
    for raw in raw_paths:
        path = Path(raw)
        if path.is_dir():
            found = sorted(path.glob("*.log"))
            if not found:
                raise FileNotFoundError(f"no .log files found in directory: {path}")
            resolved.extend(found)
        elif path.is_file():
            resolved.append(path)
        else:
            raise FileNotFoundError(f"path does not exist: {path}")
    return resolved


def iter_lines(paths: Iterable[Path]) -> Iterator[str]:
    """Yield non-empty lines from every file, streaming rather than loading all."""
    for path in paths:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                line = line.strip()
                if line:
                    yield line


def build_arg_parser() -> argparse.ArgumentParser:
    """Build the command-line interface."""
    parser = argparse.ArgumentParser(
        prog="analyze.py",
        description="Analyse web server access logs (Apache/Nginx combined format).",
    )
    parser.add_argument(
        "paths",
        nargs="+",
        metavar="PATH",
        help="log file(s), or directories containing *.log files",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Entry point. Returns the process exit code."""
    args = build_arg_parser().parse_args(argv)
    try:
        paths = resolve_paths(args.paths)
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    parsed = 0
    unparseable = 0
    for line in iter_lines(paths):
        if parse_line(line) is None:
            unparseable += 1
        else:
            parsed += 1

    print(f"parsed {parsed} line(s), {unparseable} could not be parsed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
