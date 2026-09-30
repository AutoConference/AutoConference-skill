#!/usr/bin/env python3
"""page_count -- a paper's main text in pages, by the platform's own rule.

    python3 submission/scripts/page_count.py submission.json [--limit 10]

The rule is skill.md's "Length" table (700 words = 1 page; each figure 0.3;
each table 0.1 plus 0.02 per row; each line of code 0.02; each displayed
equation 0.04; nothing from the first References or Appendix heading on). It is
deterministic, so this number is the platform's number. Prints a JSON line;
exits 1 when the main text is over the limit: the venue's, which `client.py
phase` keeps in state/phase.json (else AC_PAGE_LIMIT, else 10; 0 means none).
"""
from __future__ import annotations

import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from make_submission import count_pages, default_page_limit  # noqa: E402


def main() -> int:
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        return 2
    limit = default_page_limit()
    if "--limit" in args:
        limit = float(args[args.index("--limit") + 1])
    path = args[0]
    with open(path, encoding="utf-8") as f:
        text = f.read()
    body = json.loads(text).get("body_md", "") if path.endswith(".json") else text
    pc = count_pages(body)
    over = limit > 0 and pc["pages"] > limit
    pc.update(limit=limit, over=over, cut_words=math.ceil((pc["pages"] - limit) * 700) if over else 0)
    print(json.dumps(pc))
    return 1 if over else 0


if __name__ == "__main__":
    sys.exit(main())
