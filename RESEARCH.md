# RESEARCH.md

This file records what I had to learn while building `log-analyzer`, where I
looked, what did not work, and what I took away from it. It is not an exhaustive
search log - just the things that genuinely required research or a change of
approach.

## 1. The Apache/Nginx "combined" log format

**What I needed to learn:** the exact field order and syntax of the combined log
format, because everything downstream depends on parsing it correctly.

**Where I looked:** the Apache HTTP Server documentation on log formats
(`https://httpd.apache.org/docs/current/logs.html#combined`) and Nginx's
`ngx_http_log_module` documentation for comparison. I validated both against
real-world example lines.

**What I learned:** there are nine fields, in a fixed order:

    remote_host ident user [timestamp] "request" status bytes "referer" "user_agent"

The important subtleties:

- the timestamp is wrapped in `[...]`, not quotes;
- the request, referer and user-agent are wrapped in `"..."` and **may contain
  spaces**;
- `ident` and `user` are almost always `-`;
- `bytes` is `-` when the response had no body.

## 2. Regex vs `str.split()`

**What I needed to learn:** whether I could get away with splitting each line on
whitespace.

**What I tried first (and why it failed):** I started with `line.split()` and
indexed the fields. It works on perfectly clean lines but breaks the moment a
user-agent contains a space:

    "Mozilla/4.08 [en] (Win98; I ;Nav)"

`split()` turns that one field into five list items, so every field after it
shifts and the line is mis-parsed (or errors). Real logs contain such
user-agents constantly.

**What I learned:** describe the *structure* of the line, not the delimiters. A
regex with named groups captures each field explicitly:

    ^(?P<ip>\S+) (?P<ident>\S+) (?P<user>\S+) \[(?P<timestamp>[^\]]+)\] "(?P<request>[^"]*)" (?P<status>\d{3}) (?P<size>\S+) "(?P<referer>[^"]*)" "(?P<user_agent>[^"]*)$

Named groups also make the code more readable: `match.group("status")` beats
`match.group(6)`.

## 3. The `-` byte count (the bug I nearly shipped)

**What I needed to learn:** how to match the response-size field.

**What did not work:** matching it with `\d+`. A `500` response with an empty
body is logged as `-`, and `\d+` simply fails to match, so the whole line became
"unparseable". I found this by testing against a real error line rather than
only happy-path examples.

**What I learned:** match the field loosely (`\S+`) and interpret its content in
code - `parse_size()` maps `-` to `0` and tolerates anything else it does not
recognise. Being permissive while parsing and strict while *interpreting* is a
pattern I will reuse.

## 4. Timezone-aware timestamps with `strptime`

**What I needed to learn:** how to turn `10/Oct/2000:13:55:36 -0700` into a
usable time.

**What I found:** Python's `datetime.strptime` accepts the `%z` directive for the
`-0700` offset. Using it produces a *timezone-aware* `datetime`, instead of a
naive one that implicitly assumes local time. That matters for the "busiest
hour" statistic: a naive parse would report the wrong hour for any log not kept
in UTC.

**What I learned:** `%z` yields a fixed-offset timezone, which is exactly what
access logs record. I added a test asserting `entry.timestamp.tzinfo is not None`
so the behaviour cannot silently regress.

## 5. Streaming vs reading the whole file

**What I needed to learn:** how to read very large logs without exhausting
memory.

**What I learned:** opening the file and iterating over the handle yields one
line at a time, so memory stays flat regardless of file size. I wrapped this in
`iter_lines()` and kept the aggregation as running counters - there is never a
full list of lines in memory. (An earlier sketch collected all lines into a list
first, then summed it; the streaming version is the same amount of code and does
not fall over on a multi-GB log.)

## 6. Packaging and test discovery

**What I needed to learn:** why `python -m unittest discover` initially found
zero tests.

**What did not work:** running discovery with the tests in a bare `tests/`
directory. `unittest` will not descend into a subdirectory that is not a
package.

**What I learned:** adding an empty `tests/__init__.py` makes the directory
importable and discovery finds it. That is why the file is there - it is not
decoration.

## Sources

- Apache log format documentation (combined format).
- Nginx `ngx_http_log_module` documentation.
- Python standard-library docs for `re`, `datetime`, `collections.Counter`,
  `argparse`, and `unittest`.
