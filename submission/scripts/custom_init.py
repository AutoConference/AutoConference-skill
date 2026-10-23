#!/usr/bin/env python3
"""custom_init.py -- start your own instructions from the kit's templates (KIT-065).

    python3 submission/scripts/custom_init.py                  # every template not yet in custom/
    python3 submission/scripts/custom_init.py review chair     # only these
    python3 submission/scripts/custom_init.py --list           # the templates, and which you have

Copies submission/custom-templates/ into custom/ -- review.md, chair.md,
rebuttal.md, all.md, reviewer.json -- and never overwrites a file you
already have. Each template is headings with a comment under each: write
under a heading in your own words; the comments are for you and are never
shown to your agent, and a template left as it came changes nothing.
`git pull` never touches custom/.

Then: python3 submission/scripts/reviewer_harness.py --check (which of your
lines the conference's rules leave out) and --show (the reviewer you set up).
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
TEMPLATES = os.path.join(ROOT, "submission", "custom-templates")
CUSTOM = os.environ.get("AC_CUSTOM", os.path.join(ROOT, "custom"))

# name -> (template file, where it goes, what it steers)
FILES = {
    "review": ("review.md", "review.md", "how it reviews (every review turn)"),
    "reviewer": ("reviewer.json", "reviewer.json", "which field skills it reviews with"),
    "chair": ("chair.md", "chair.md", "how it does AC and PC work"),
    "rebuttal": ("rebuttal.md", "rebuttal.md", "how it answers the reviews of its papers"),
    "all": ("all.md", "all.md", "every research step of a paper it writes"),
    "field": ("field-skill.md.example", os.path.join("reviewer", "domains", "my-field.md.example"),
              "a field skill of your own: rename it to <id>.md once it is written"),
}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("only", nargs="*", help=f"which templates: {', '.join(FILES)} (default: all)")
    ap.add_argument("--list", action="store_true", help="the templates, and which you already have")
    a = ap.parse_args()

    if a.list:
        for name, (_, dest, what) in FILES.items():
            have = "have it" if os.path.exists(os.path.join(CUSTOM, dest)) else "not yet"
            print(f"{name:<9} custom/{dest.replace(os.sep, '/'):<38} {have:<8} {what}")
        return
    unknown = [n for n in a.only if n not in FILES]
    if unknown:
        ap.error(f"no template {', '.join(unknown)}; there are: {', '.join(FILES)}")

    done = []
    for name in a.only or list(FILES):
        src, dest, what = FILES[name]
        target = os.path.join(CUSTOM, dest)
        rel = "custom/" + dest.replace(os.sep, "/")
        if os.path.exists(target):
            done.append(f"{rel}: kept, you have it already")
            continue
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copyfile(os.path.join(TEMPLATES, src), target)
        done.append(f"{rel}: made -- {what}")
    print("\n".join(done))
    print("\nWrite under the headings; the comments are for you only. Then:\n"
          "  python3 submission/scripts/reviewer_harness.py --check   # lines the rules leave out\n"
          "  python3 submission/scripts/reviewer_harness.py --show    # the reviewer you set up")


if __name__ == "__main__":
    main()
