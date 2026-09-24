#!/usr/bin/env python3
"""mini_jq -- the few jq filters run-pipeline.sh uses, for machines without jq.

    mini_jq.py -r '.statistics.min_n_per_cell' quality.json
    mini_jq.py -r '.paper_shape.forbidden_in_title[]' quality.json
    mini_jq.py -r '.study_kind // empty' FEASIBILITY.json

run-pipeline.sh falls back to this only when `jq` is not on PATH. It supports
a dotted path, an optional trailing `[]`, and `// empty`; anything else is an
error rather than a guess.
"""
import json
import sys


def main() -> int:
    args = [a for a in sys.argv[1:] if a != "-r"]
    if not args:
        print("usage: mini_jq.py -r FILTER [FILE]", file=sys.stderr)
        return 2
    flt, path = args[0].strip(), (args[1] if len(args) > 1 else None)
    doc = json.load(open(path, encoding="utf-8") if path else sys.stdin)

    empty_ok = flt.endswith("// empty")
    if empty_ok:
        flt = flt[: -len("// empty")].strip()
    each = flt.endswith("[]")
    if each:
        flt = flt[:-2]
    if not flt.startswith("."):
        print(f"mini_jq: unsupported filter {args[0]!r}", file=sys.stderr)
        return 2

    v = doc
    for key in [k for k in flt[1:].split(".") if k]:
        v = v.get(key) if isinstance(v, dict) else None
    if v is None:
        if not empty_ok:
            print("null")
        return 0
    for item in (v if each else [v]):
        print(item if isinstance(item, str) else json.dumps(item))
    return 0


if __name__ == "__main__":
    sys.exit(main())
