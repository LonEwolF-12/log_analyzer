#!/usr/bin/env python3
"""Generate a deterministic sample access log for demos and manual testing.

Running this script writes ``sample.log`` next to itself. The random seed is
fixed, so repeated runs produce byte-for-byte identical output - which keeps
examples in the README stable and makes the tool easy to demo.

Usage::

    python sample/generate_sample.py
"""

import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

SEED = 20261012
LINE_COUNT = 300
START = datetime(2026, 10, 12, 8, 0, 0, tzinfo=timezone.utc)
OUTPUT = Path(__file__).with_name("sample.log")

# (method, path, status, weight)
REQUESTS = [
    ("GET", "/", 200, 30),
    ("GET", "/index.html", 200, 25),
    ("GET", "/assets/app.css", 200, 20),
    ("GET", "/assets/app.js", 200, 20),
    ("GET", "/api/v1/products", 200, 18),
    ("GET", "/api/v1/orders", 200, 15),
    ("POST", "/api/v1/orders", 201, 10),
    ("GET", "/api/v1/health", 200, 8),
    ("GET", "/login", 200, 6),
    ("GET", "/old-page", 404, 5),
    ("GET", "/promo", 404, 4),
    ("GET", "/api/v1/orders", 500, 3),
    ("POST", "/api/v1/payments", 502, 2),
]

# (ip, weight)
CLIENTS = [
    ("203.0.113.7", 20),
    ("198.51.100.23", 15),
    ("192.0.2.44", 12),
    ("10.0.0.15", 10),
    ("203.0.113.99", 8),
    ("198.51.100.5", 6),
    ("10.0.0.42", 5),
]

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
    "Mozilla/5.0 (X11; Linux x86_64)",
    "curl/7.68.0",
]

SIZES = [0, 512, 1024, 2048, 5120, 15360]

# A couple of non-access lines a real log often contains: these exercise the
# "unparseable" counter (they are not in combined format) and the error-keyword
# counter (they contain the word "ERROR").
EXTRA_LINES = [
    "2026-10-12 08:00:03,120 INFO  server listening on 0.0.0.0:8080",
    "2026-10-12 13:41:07,882 ERROR failed to connect to redis: connection refused",
]


def main() -> None:
    rng = random.Random(SEED)
    methods = [row[0] for row in REQUESTS]
    paths = [row[1] for row in REQUESTS]
    statuses = [row[2] for row in REQUESTS]
    request_weights = [row[3] for row in REQUESTS]
    client_ips = [row[0] for row in CLIENTS]
    client_weights = [row[1] for row in CLIENTS]

    timestamp = START
    lines: list[str] = []
    for _ in range(LINE_COUNT):
        i = rng.choices(range(len(REQUESTS)), weights=request_weights)[0]
        ip = rng.choices(client_ips, weights=client_weights)[0]
        agent = rng.choice(USER_AGENTS)
        size = rng.choice(SIZES)
        timestamp += timedelta(seconds=rng.randint(1, 90))
        stamp = timestamp.strftime("%d/%b/%Y:%H:%M:%S %z")
        lines.append(
            f'{ip} - - [{stamp}] "{methods[i]} {paths[i]} HTTP/1.1" '
            f'{statuses[i]} {size} "-" "{agent}"'
        )

    for offset, text in enumerate(EXTRA_LINES):
        lines.insert(min(len(lines), 20 + offset * 140), text)

    OUTPUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {len(lines)} lines to {OUTPUT}")


if __name__ == "__main__":
    main()
