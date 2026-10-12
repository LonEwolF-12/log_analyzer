"""Unit tests for the log-analyzer tool.

Run them with either of:

    python -m unittest discover -v
    python -m unittest tests.test_analyze -v
"""

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

# Make the project root importable no matter which working directory the test
# runner is invoked from.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import analyze  # noqa: E402  (import after sys.path tweak, on purpose)

VALID_LINE = (
    '127.0.0.1 - frank [10/Oct/2000:13:55:36 -0700] '
    '"GET /apache_pb.gif HTTP/1.0" 200 2326 '
    '"http://www.example.com/start.html" "Mozilla/4.08 [en] (Win98; I ;Nav)"'
)
SERVER_ERROR_LINE = (
    '203.0.113.5 - - [10/Oct/2000:13:56:01 -0700] '
    '"POST /api/v1/orders HTTP/1.1" 500 - "-" "curl/7.68.0"'
)
CLIENT_ERROR_LINE = (
    '10.0.0.9 - - [10/Oct/2000:14:00:12 -0700] '
    '"GET /missing HTTP/1.1" 404 0 "-" "curl/7.68.0"'
)
GARBAGE_LINE = "this is not a combined-format log line"
ERROR_KEYWORD_LINE = "2026-10-12 13:41:07,882 ERROR failed to connect to redis"


def build_report(lines):
    """Write ``lines`` to a temporary log file and return the analysed Report."""
    with tempfile.TemporaryDirectory() as tmp:
        log = Path(tmp) / "access.log"
        log.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return analyze.analyze([log])


class ParseLineTests(unittest.TestCase):
    def test_valid_line_parses_every_field(self):
        entry = analyze.parse_line(VALID_LINE)
        self.assertIsNotNone(entry)
        self.assertEqual(entry.ip, "127.0.0.1")
        self.assertEqual(entry.method, "GET")
        self.assertEqual(entry.path, "/apache_pb.gif")
        self.assertEqual(entry.protocol, "HTTP/1.0")
        self.assertEqual(entry.status, 200)
        self.assertEqual(entry.size, 2326)

    def test_user_agent_with_spaces_is_kept_intact(self):
        # This is the field that makes str.split() unsuitable.
        entry = analyze.parse_line(VALID_LINE)
        self.assertEqual(entry.user_agent, "Mozilla/4.08 [en] (Win98; I ;Nav)")

    def test_timestamp_is_timezone_aware(self):
        entry = analyze.parse_line(VALID_LINE)
        self.assertEqual(entry.timestamp.hour, 13)
        self.assertIsNotNone(entry.timestamp.tzinfo)

    def test_dash_byte_count_becomes_zero(self):
        entry = analyze.parse_line(SERVER_ERROR_LINE)
        self.assertEqual(entry.size, 0)

    def test_garbage_line_returns_none(self):
        self.assertIsNone(analyze.parse_line(GARBAGE_LINE))


class FieldParserTests(unittest.TestCase):
    def test_parse_size(self):
        self.assertEqual(analyze.parse_size("2326"), 2326)
        self.assertEqual(analyze.parse_size("-"), 0)
        self.assertEqual(analyze.parse_size("nonsense"), 0)

    def test_parse_request_splits_method_path_protocol(self):
        self.assertEqual(
            analyze.parse_request("GET /a HTTP/1.1"), ("GET", "/a", "HTTP/1.1")
        )
        self.assertEqual(analyze.parse_request("GET /a"), ("GET", "/a", ""))
        self.assertEqual(analyze.parse_request(""), ("", "", ""))

    def test_parse_timestamp_handles_invalid_input(self):
        self.assertIsNone(analyze.parse_timestamp("not-a-timestamp"))


class AnalyzeTests(unittest.TestCase):
    def test_counts_parsed_and_unparseable_lines(self):
        report = build_report(
            [VALID_LINE, SERVER_ERROR_LINE, CLIENT_ERROR_LINE, GARBAGE_LINE, ERROR_KEYWORD_LINE]
        )
        self.assertEqual(report.lines_read, 5)
        self.assertEqual(report.parsed, 3)
        self.assertEqual(report.unparseable, 2)

    def test_error_keyword_lines_are_counted(self):
        report = build_report([VALID_LINE, ERROR_KEYWORD_LINE])
        self.assertEqual(report.error_lines, 1)

    def test_status_and_error_breakdown(self):
        report = build_report([VALID_LINE, SERVER_ERROR_LINE, CLIENT_ERROR_LINE])
        self.assertEqual(report.status_counts[200], 1)
        self.assertEqual(report.status_counts[500], 1)
        self.assertEqual(report.status_counts[404], 1)
        client_errors, server_errors = report.error_status_counts
        self.assertEqual(client_errors, 1)
        self.assertEqual(server_errors, 1)

    def test_total_bytes_ignores_dash_entries(self):
        report = build_report([VALID_LINE, SERVER_ERROR_LINE])
        self.assertEqual(report.total_bytes, 2326)

    def test_empty_input_does_not_raise(self):
        report = build_report([])
        self.assertEqual(report.lines_read, 0)
        self.assertEqual(report.parsed_ratio, 0.0)


class FormatTests(unittest.TestCase):
    def setUp(self):
        self.report = build_report(
            [VALID_LINE, SERVER_ERROR_LINE, CLIENT_ERROR_LINE, GARBAGE_LINE]
        )

    def test_text_contains_key_sections(self):
        text = analyze.format_text(self.report, top_n=3)
        self.assertIn("Log Analysis Report", text)
        self.assertIn("Status codes", text)
        self.assertIn("server error(s) (5xx)", text)

    def test_json_is_valid_and_structured(self):
        payload = json.loads(analyze.format_json(self.report, top_n=2))
        self.assertEqual(payload["parsed"], 3)
        self.assertEqual(payload["unparseable"], 1)
        self.assertEqual(payload["status_codes"]["500"], 1)
        self.assertEqual(payload["busiest_hour"]["hour"], 13)
        self.assertLessEqual(len(payload["top_ips"]), 2)

    def test_markdown_has_tables(self):
        markdown = analyze.format_markdown(self.report, top_n=2)
        self.assertIn("# Log Analysis Report", markdown)
        self.assertIn("| Status | Count | Share |", markdown)


class ResolvePathsTests(unittest.TestCase):
    def test_missing_path_raises(self):
        with self.assertRaises(FileNotFoundError):
            analyze.resolve_paths(["does-not-exist.log"])

    def test_directory_expands_to_log_files_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "a.log").write_text(VALID_LINE + "\n", encoding="utf-8")
            (Path(tmp) / "b.log").write_text(VALID_LINE + "\n", encoding="utf-8")
            (Path(tmp) / "notes.txt").write_text("ignore me\n", encoding="utf-8")
            resolved = analyze.resolve_paths([tmp])
            self.assertEqual(len(resolved), 2)
            self.assertTrue(all(path.suffix == ".log" for path in resolved))

    def test_directory_without_logs_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FileNotFoundError):
                analyze.resolve_paths([tmp])


class CliTests(unittest.TestCase):
    def test_main_returns_zero_and_prints_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "access.log"
            log.write_text(VALID_LINE + "\n", encoding="utf-8")
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                code = analyze.main([str(log)])
            self.assertEqual(code, 0)
            self.assertIn("Log Analysis Report", buffer.getvalue())

    def test_main_returns_two_on_missing_path(self):
        with redirect_stderr(io.StringIO()):
            code = analyze.main(["definitely-missing.log"])
        self.assertEqual(code, 2)

    def test_main_rejects_non_positive_top_n(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "access.log"
            log.write_text(VALID_LINE + "\n", encoding="utf-8")
            with redirect_stderr(io.StringIO()):
                code = analyze.main([str(log), "--top-n", "0"])
            self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
