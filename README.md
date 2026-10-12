# log-analyzer

A small, dependency-free command-line tool that reads web server access logs
(Apache / Nginx **combined** format), aggregates them, and prints an
**actionable** report: which status codes are failing, which clients and paths
dominate, and when the traffic peaks.

Built as my submission for the **Enterprise Automation Services** trainee /
junior DevOps engineer technical challenge.

---

## What it does and why

Logs are the first place I look when something goes wrong, and they are the raw
material behind the Grafana dashboards and Sentry alerts I have built and used
at work. I wanted to build the layer *underneath* those dashboards: the part
that turns a wall of access-log text into the handful of numbers that actually
tell you whether a service is healthy.

The tool takes one or more log files as **input**, parses and aggregates them,
and produces a **report** you can read at a glance (or pipe into another tool as
JSON).

Specifically, for a set of access logs it reports:

- how many lines were read, parsed, and could **not** be parsed;
- how many lines look like errors (by keyword), for looser / non-standard logs;
- the **HTTP status-code breakdown**, with explicit warnings for 4xx and 5xx;
- the **top N client IPs**, **request paths**, and **HTTP methods**;
- the **busiest hour**;
- the **total bytes** served.

## Requirements

- Python **3.9+** (developed and tested on 3.13)
- No third-party packages - the standard library only.

## How to run it

There is nothing to install. Clone the repo and run:

    # Analyse the bundled sample log (text report)
    python analyze.py sample/sample.log

    # More detail, different format
    python analyze.py sample/sample.log --top-n 10 --format json

    # Every *.log file in a directory, saved to a Markdown file
    python analyze.py /var/log/nginx --format markdown --output report.md

Full option list (`python analyze.py --help`):

    usage: analyze.py [-h] [-n N] [-f {json,markdown,text}] [-o FILE] PATH [PATH ...]

    positional arguments:
      PATH                  log file(s), or directories containing *.log files

    options:
      -h, --help            show this help message and exit
      -n, --top-n N         show the top N entries in each ranking (default: 5)
      -f, --format {json,markdown,text}
                            output format (default: text)
      -o, --output FILE     write the report to FILE instead of stdout

Exit codes: `0` on success, `2` for a missing path or invalid arguments (handy
in scripts and CI jobs).

Example report (`python analyze.py sample/sample.log`):

    ======================================================================
                              Log Analysis Report
    ======================================================================
     Sources          : sample/sample.log
     Lines read       : 302
     Parsed           : 300 (99.3%)
     Unparseable      : 2
     Error-keyword    : 1
     Total bytes sent : 1,235,456

     Status codes
     ----------------------------------------------------------------------
       200       253  ( 84.3%)
       201        18  (  6.0%)
       404        15  (  5.0%)
       500        10  (  3.3%)
       502         4  (  1.3%)
       !! 14 server error(s) (5xx) - investigate immediately
       !! 15 client error(s) (4xx) - check for broken links / bad requests

     Top 5 client IPs
     ----------------------------------------------------------------------
       203.0.113.7                                        64
       192.0.2.44                                         58
       198.51.100.23                                      58
       10.0.0.15                                          39
       203.0.113.99                                       38

     Busiest hour     : 09:00 - 79 request(s)
    ======================================================================

## How it works

The pipeline is simple, and each stage is a small, individually testable
function:

    read lines  ->  parse each line  ->  aggregate into counters  ->  render a report

1. **Read lines** (`iter_lines`) - files are streamed line by line, so memory use
   does not grow with the size of the log (a multi-GB file is fine).
2. **Parse** (`parse_line`) - each line is matched against a regex for the
   combined log format. A match becomes a `LogEntry`; a non-match returns `None`
   and is counted as *unparseable* rather than crashing the run.
3. **Aggregate** (`analyze`) - parsed entries are folded into
   `collections.Counter` objects (status codes, IPs, paths, methods, hours).
4. **Render** (`format_text` / `format_json` / `format_markdown`) - the counters
   become the report.

### Why a regex and not `str.split()`?

The combined format has nine fields, but three of them - the request, the
referer and the user-agent - are wrapped in quotes and **can contain spaces**.
Real user-agents almost always do:

    "Mozilla/4.08 [en] (Win98; I ;Nav)"

Splitting on whitespace would break those fields apart and shift everything
after them. The regex describes the *structure* of the line instead:

    ^(?P<ip>\S+) (?P<ident>\S+) (?P<user>\S+) \[(?P<timestamp>[^\]]+)\] "(?P<request>[^"]*)" (?P<status>\d{3}) (?P<size>\S+) "(?P<referer>[^"]*)" "(?P<user_agent>[^"]*)$

Note the byte count uses `\S+`, not `\d+`, because the format writes `-` when a
request returns no body.

## Output formats

- **text** (default) - a human-readable report for the terminal.
- **json** - a structured report for piping into `jq`, a script, or a dashboard.
- **markdown** - tables you can paste into a PR, issue, or README.

## Testing

The test suite uses only the standard library:

    python -m unittest discover -v

The 22 tests cover the parser (including the space-containing user-agent and the
`-` byte placeholder), timestamp parsing, every aggregation, all three output
formats, path resolution, and the CLI including its exit codes.

## Project structure

    log-analyzer/
    ├── analyze.py                 # the whole tool (single file, easy to follow)
    ├── sample/
    │   ├── generate_sample.py     # deterministic sample-log generator
    │   └── sample.log             # 300+ line sample produced by the generator
    ├── tests/
    │   ├── __init__.py
    │   └── test_analyze.py        # 22 unit tests
    ├── README.md
    ├── RESEARCH.md                # what I learned along the way
    ├── AI.md                      # how I used AI tools and verified them
    └── .gitignore

## Design decisions

- **Standard library only.** No install step means the tool runs anywhere Python
  does, which matters for a small ops utility.
- **Single file.** The whole program fits in one readable module; a package
  would add structure without adding clarity at this size.
- **Stream, don't load.** Reading line by line keeps memory flat on huge logs.
- **Never crash on bad input.** Real logs contain junk. Unparseable lines are
  counted and skipped, so one bad line cannot sink a whole run.
- **Fail loudly on bad arguments.** A missing path or invalid `--top-n` returns a
  non-zero exit code and a clear message - what you want in a script or CI job.

## What I would improve with more time

- **Configurable log format.** Only the combined format is supported today; a
  `--pattern` option (or named formats) would let it handle custom Nginx
  `log_format` lines and application logs.
- **Response-time statistics.** The standard combined format has no response
  time; supporting Nginx's `$request_time` would enable p50/p95/p99 latency.
- **Time-window filtering** (`--since` / `--until`) for investigating incidents.
- **Follow mode / alerting.** e.g. `--follow` to tail a file and warn when 5xx
  crosses a threshold - a step towards real monitoring.
- **CI.** A GitHub Actions workflow running the tests on every push. I kept CI
  out of scope to stay within the time budget, but it is the natural next step.

## Notes

- Timestamps are parsed with their timezone offset (`%z`) preserved, so the
  "busiest hour" reflects the hour recorded in the log rather than assuming UTC.
- `--top-n` applies to every ranking section (IPs, paths, methods).
