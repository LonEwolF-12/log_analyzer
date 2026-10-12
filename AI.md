# AI.md

I used AI tools as a pair-programmer / rubber duck during this challenge. Below
is an honest account of what I used them for, what they got wrong, and how I
checked their output. Everything in the repository is code I understand and can
explain line by line.

## Tools used

- **Cline (an AI coding agent in VS Code)** - to help scaffold the project,
  draft boilerplate (the `argparse` setup, the report formatting helpers), and to
  sanity-check my reasoning about the log format and Python standard-library
  APIs.
- **GitHub Copilot-style inline suggestions** - for small completions while
  writing the regex and the dataclasses.

## What I used AI for

1. **Scaffolding and boilerplate.** Generating the initial skeleton of the CLI
   (argument parsing, the `if __name__ == "__main__"` block, the `Report`
   dataclass) so I could spend my attention on the parsing logic.
2. **A second opinion on the regex.** I described the combined log format and
   asked for a parsing regex, then compared it against my own.
3. **Explaining standard-library details.** e.g. confirming that
   `datetime.strptime`'s `%z` directive keeps the timezone offset, and how
   `collections.Counter.most_common` orders ties.

## Where the AI was wrong or unhelpful

- **A regex that assumed integers for the byte count.** An early suggested
  pattern used `(\d+)` for the response size. That is wrong: the combined format
  writes `-` when a request returns no body (e.g. a 500 with an empty response).
  I caught this by testing against a real 500 line and changed it to `(\S+)`,
  with the `-` handled explicitly in `parse_size`.
- **`str.split()` "simplifications".** A suggestion to replace the regex with a
  simple whitespace split "because the format is just space-separated". That
  breaks on any user-agent containing a space, which is most of them. I kept the
  regex and wrote a test that uses a user-agent with spaces to prove why.
- **Timezone naivety.** An early draft dropped the `%z` offset and produced
  naive datetimes. That would make the "busiest hour" wrong for logs not in UTC.
  I fixed it and added a test asserting the parsed timestamp is timezone-aware.

## How I verified AI suggestions

- **Ran them.** Every snippet was executed against real input before it stayed
  in the codebase; nothing was accepted purely because it *looked* right.
- **Tested the edge cases the AI missed.** The `-` byte count, the
  space-containing user-agent, and garbage lines are all covered by explicit
  unit tests in `tests/test_analyze.py`.
- **Cross-checked against a primary source.** For the log format itself I
  trusted the Apache documentation rather than the AI, and checked the AI's
  claims about it against that page.
- **Read it before I kept it.** If I could not explain why a line was there, I
  rewrote it until I could - the goal was a project I fully understand.
