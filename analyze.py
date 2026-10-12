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


@dataclass
class Report:
    """Aggregated statistics gathered from one analysis run."""

    sources: list[str] = field(default_factory=list)
    lines_read: int = 0
    parsed: int = 0
    unparseable: int = 0
    error_lines: int = 0
    total_bytes: int = 0
    status_counts: Counter = field(default_factory=Counter)
    method_counts: Counter = field(default_factory=Counter)
    ip_counts: Counter = field(default_factory=Counter)
    path_counts: Counter = field(default_factory=Counter)
    hour_counts: Counter = field(default_factory=Counter)
    user_agent_counts: Counter = field(default_factory=Counter)

    @property
    def parsed_ratio(self) -> float:
        """Fraction of read lines that parsed successfully (0.0 - 1.0)."""
        return self.parsed / self.lines_read if self.lines_read else 0.0

    @property
    def error_status_counts(self) -> tuple[int, int]:
        """Return ``(client_errors, server_errors)`` for 4xx and 5xx statuses."""
        client = sum(c for s, c in self.status_counts.items() if 400 <= s < 500)
        server = sum(c for s, c in self.status_counts.items() if 500 <= s < 600)
        return client, server


def analyze(paths: Sequence[Path]) -> Report:
    """Read every file in ``paths`` and build a :class:`Report`.

    Lines are processed one at a time (streaming) so the tool's memory use does
    not grow with the size of the input. Unparseable lines are counted rather
    than raising, so a dirty log still produces a usable report.
    """
    report = Report(sources=[str(path) for path in paths])
    for line in iter_lines(paths):
        report.lines_read += 1
        lowered = line.lower()
        if any(keyword in lowered for keyword in ERROR_KEYWORDS):
            report.error_lines += 1

        entry = parse_line(line)
        if entry is None:
            report.unparseable += 1
            continue

        report.parsed += 1
        report.total_bytes += entry.size
        report.status_counts[entry.status] += 1
        report.method_counts[entry.method] += 1
        report.ip_counts[entry.ip] += 1
        report.path_counts[entry.path] += 1
        report.user_agent_counts[entry.user_agent] += 1
        if entry.timestamp is not None:
            report.hour_counts[entry.timestamp.hour] += 1
    return report


REPORT_WIDTH = 70


def _rule(char: str = "=") -> str:
    return char * REPORT_WIDTH


def _top_table(title: str, counter: Counter, top_n: int) -> list[str]:
    """Render a ranked 'Top N' block for the given counter."""
    rows = [f" {title}", f" {_rule('-')}"]
    if not counter:
        rows.append("   (none)")
    for key, count in counter.most_common(top_n):
        label = str(key) if str(key) else "(empty)"
        rows.append(f"   {label[:44]:<44} {count:>8,}")
    rows.append("")
    return rows


def format_text(report: Report, top_n: int = 5) -> str:
    """Render the report as a human-readable text block."""
    rows: list[str] = [
        _rule("="),
        " Log Analysis Report".center(REPORT_WIDTH),
        _rule("="),
        f" Sources          : {', '.join(report.sources)}",
        f" Lines read       : {report.lines_read:,}",
        f" Parsed           : {report.parsed:,} ({report.parsed_ratio * 100:.1f}%)",
        f" Unparseable      : {report.unparseable:,}",
        f" Error-keyword    : {report.error_lines:,}",
        f" Total bytes sent : {report.total_bytes:,}",
        "",
    ]

    rows.append(" Status codes")
    rows.append(f" {_rule('-')}")
    if not report.status_counts:
        rows.append("   (none)")
    for status, count in report.status_counts.most_common():
        share = (count / report.parsed * 100) if report.parsed else 0.0
        rows.append(f"   {status}  {count:>8,}  ({share:5.1f}%)")
    client_errors, server_errors = report.error_status_counts
    if server_errors:
        rows.append(f"   !! {server_errors:,} server error(s) (5xx) - investigate immediately")
    if client_errors:
        rows.append(f"   !! {client_errors:,} client error(s) (4xx) - check for broken links / bad requests")
    rows.append("")

    rows += _top_table(f"Top {top_n} client IPs", report.ip_counts, top_n)
    rows += _top_table(f"Top {top_n} request paths", report.path_counts, top_n)
    rows += _top_table(f"Top {top_n} methods", report.method_counts, top_n)

    if report.hour_counts:
        hour, count = report.hour_counts.most_common(1)[0]
        rows.append(f" Busiest hour     : {hour:02d}:00 - {count:,} request(s)")
    rows.append(_rule("="))
    return "\n".join(rows)


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
    parser.add_argument(
        "-n",
        "--top-n",
        type=int,
        default=5,
        metavar="N",
        help="show the top N entries in each ranking (default: 5)",
    )
    parser.add_argument(
        "-o",
        "--output",
        metavar="FILE",
        help="write the report to FILE instead of stdout",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Entry point. Returns the process exit code."""
    args = build_arg_parser().parse_args(argv)
    if args.top_n < 1:
        print("error: --top-n must be at least 1", file=sys.stderr)
        return 2
    try:
        paths = resolve_paths(args.paths)
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    report = analyze(paths)
    output = format_text(report, top_n=args.top_n)

    if args.output:
        Path(args.output).write_text(output + "\n", encoding="utf-8")
        print(f"report written to {args.output}")
    else:
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
