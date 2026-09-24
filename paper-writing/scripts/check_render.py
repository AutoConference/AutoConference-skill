#!/usr/bin/env python3
"""Layout gate on the compiled PDF, not the source.

Every other gate in this skill reads LaTeX source or a `.bib` file. None of
them ever look at the rendered page, so none of them can see an unresolved
cross-reference, two boxes drawn on top of each other, or a line of text
that runs past the page's own margin -- all of which compile cleanly and
read correctly as source. This is the missing step, added after three
passing text gates shipped a paper with a printed `??` and a page-1 teaser
with overlapping text.

    python3 scripts/check_render.py output/pdf/paper.pdf
    python3 scripts/check_render.py output/pdf/paper.pdf --json

Detects, using only `pdftotext -bbox-layout` word boxes and plain text:

  unresolved_ref   a literal "??" printed on a page (an undefined \\ref,
                   \\eqref, \\pageref, or \\cite that LaTeX could not
                   resolve, and compiled anyway).
  text_overlap     two words whose bounding boxes substantially intersect --
                   real double-drawn content, not kerning, a ligature, or a
                   math subscript sitting close to its base symbol.
  margin_overflow  a word extending past this document's own established
                   left/right text column (derived from the document itself,
                   not a hard-coded venue margin) by more than a small,
                   fixed tolerance.

In a two-column layout the established column runs from the left column's
left edge to the right column's right edge, so a float that overflows only
into the *gutter* between the columns is not reported as a margin overflow.
Nothing in a PDF distinguishes that from a legitimate full-width `figure*`
or `table*`, which crosses the gutter by design; what a real gutter overflow
almost always also does is collide with the other column's text, and that is
reported as `text_overlap`. Look at the rendered pages of a two-column paper
with this in mind.

Deliberately does not check vertical (top/bottom) overflow: the NeurIPS
style's own page-1 notice string and every page's folio (page number) both
legitimately sit below the nominal text height, and no tolerance separates
those from a genuine bottom-of-page overflow without hard-coding template
internals into a layout gate. A table or figure that overflows only the
bottom of the page, on a page other than one, is a known blind spot; see
the module docstring in the paper-writing skill's audit-protocol.md.

Read-only. Never edits the PDF or anything upstream of it. Requires
`pdftotext` (poppler-utils) on PATH; nothing else.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

# A "word" pdftotext hands back is a candidate for the overlap check only if
# it looks like prose rather than a fragment of typeset math. Math mode
# routinely produces short, tightly-kerned glyph runs next to their own
# subscripts and superscripts ("max" beside "m,i", "C(H)" beside the brace
# of an \underbrace annotation) whose boxes legitimately intersect; a real
# double-drawn defect never needs a bracket, and is never one character.
MATH_LIKE_CHARS = set("(){}[]|\\^_$<>=+*/")
MIN_OVERLAP_FRACTION = 0.20
MIN_MARGIN_TOLERANCE = 10.0  # pt; see calibration note in the report.

WORD_RE = re.compile(
    r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">'
    r"([^<]*)</word>"
)
PAGE_RE = re.compile(
    r'<page width="([\d.]+)" height="([\d.]+)">(.*?)</page>', re.S
)


class Word:
    __slots__ = ("x0", "y0", "x1", "y1", "text")

    def __init__(self, x0: float, y0: float, x1: float, y1: float, text: str):
        self.x0, self.y0, self.x1, self.y1 = x0, y0, x1, y1
        self.text = text

    @property
    def area(self) -> float:
        return max(0.0, self.x1 - self.x0) * max(0.0, self.y1 - self.y0)


def require_pdftotext() -> None:
    if shutil.which("pdftotext") is None:
        sys.exit(
            "pdftotext not found on PATH (poppler-utils). "
            "check_render.py has no other way to read a compiled PDF."
        )


def run_pdftotext(pdf: Path, *extra_args: str) -> str:
    proc = subprocess.run(
        ["pdftotext", *extra_args, str(pdf), "-"],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        sys.exit(f"pdftotext failed on {pdf}:\n{proc.stderr.strip()}")
    return proc.stdout


def parse_pages(bbox_output: str) -> list[list[Word]]:
    pages = []
    for _w, _h, body in PAGE_RE.findall(bbox_output):
        words = [
            Word(float(x0), float(y0), float(x1), float(y1), html.unescape(txt))
            for x0, y0, x1, y1, txt in WORD_RE.findall(body)
        ]
        pages.append(words)
    return pages


def split_plain_pages(plain_output: str) -> list[str]:
    # pdftotext separates pages with a form feed; a trailing one after the
    # last page yields a harmless empty final element.
    pages = plain_output.split("\f")
    if pages and pages[-1] == "":
        pages.pop()
    return pages


def is_overlap_candidate(w: Word) -> bool:
    if len(w.text) < 2:
        return False
    if any(c in MATH_LIKE_CHARS for c in w.text):
        return False
    return any(c.isalpha() for c in w.text)


def overlap_fraction(a: Word, b: Word) -> float:
    x0, x1 = max(a.x0, b.x0), min(a.x1, b.x1)
    y0, y1 = max(a.y0, b.y0), min(a.y1, b.y1)
    if x1 <= x0 or y1 <= y0:
        return 0.0
    inter = (x1 - x0) * (y1 - y0)
    smaller = min(a.area, b.area)
    return inter / smaller if smaller > 0 else 0.0


def find_unresolved_refs(plain_pages: list[str]) -> list[dict]:
    findings = []
    for pageno, text in enumerate(plain_pages, start=1):
        for m in re.finditer(r".{0,24}\?\?.{0,24}", text):
            snippet = " ".join(m.group(0).split())
            findings.append({
                "type": "unresolved_ref",
                "page": pageno,
                "detail": f'printed "??" near: "{snippet}"',
            })
    return findings


def find_text_overlaps(pages: list[list[Word]], threshold: float) -> list[dict]:
    findings = []
    for pageno, words in enumerate(pages, start=1):
        candidates = [w for w in words if is_overlap_candidate(w)]
        n = len(candidates)
        parent = list(range(n))

        def find(i: int) -> int:
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        def union(i: int, j: int) -> None:
            ri, rj = find(i), find(j)
            if ri != rj:
                parent[ri] = rj

        pairs: list[tuple[float, Word, Word, int]] = []
        for i in range(n):
            for j in range(i + 1, n):
                frac = overlap_fraction(candidates[i], candidates[j])
                if frac >= threshold:
                    union(i, j)
                    pairs.append((frac, candidates[i], candidates[j], i))
        # Group pairs by final connected component so one visual defect --
        # which usually overlaps many word pairs at once -- is reported
        # once, not once per pair. `find` is only stable to key by after
        # every union above has already been applied.
        clusters: dict[int, list[tuple[float, Word, Word]]] = {}
        for frac, a, b, i in pairs:
            clusters.setdefault(find(i), []).append((frac, a, b))
        for items in clusters.values():
            items.sort(key=lambda t: -t[0])
            frac, a, b = items[0]
            findings.append({
                "type": "text_overlap",
                "page": pageno,
                "detail": (
                    f"'{a.text}' overlaps '{b.text}' "
                    f"({frac:.0%} of the smaller box's area"
                    + (f"; {len(items)} word pairs collide here" if len(items) > 1 else "")
                    + ")"
                ),
            })
    return findings


def percentile(values: list[float], p: float) -> float:
    s = sorted(values)
    k = (len(s) - 1) * p
    f, c = int(k), min(int(k) + 1, len(s) - 1)
    if f == c:
        return s[f]
    return s[f] + (s[c] - s[f]) * (k - f)


def find_margin_overflows(pages: list[list[Word]], tolerance: float) -> list[dict]:
    all_words = [w for page in pages for w in page]
    if len(all_words) < 50:
        return []  # too little text to establish a reliable margin
    left = percentile([w.x0 for w in all_words], 0.01)
    right = percentile([w.x1 for w in all_words], 0.99)
    findings = []
    for pageno, words in enumerate(pages, start=1):
        offenders = [
            w for w in words if w.x0 < left - tolerance or w.x1 > right + tolerance
        ]
        if not offenders:
            continue
        worst = max(
            offenders,
            key=lambda w: max(left - tolerance - w.x0, w.x1 - (right + tolerance)),
        )
        over_left = max(0.0, left - worst.x0)
        over_right = max(0.0, worst.x1 - right)
        findings.append({
            "type": "margin_overflow",
            "page": pageno,
            "detail": (
                f"'{worst.text}' runs {max(over_left, over_right):.1f}pt past "
                f"the established text column (left={left:.1f}, right={right:.1f})"
                + (f"; {len(offenders)} words affected on this page" if len(offenders) > 1 else "")
            ),
        })
    return findings


def check(pdf: Path, overlap_threshold: float, margin_tolerance: float) -> dict:
    bbox_output = run_pdftotext(pdf, "-bbox-layout")
    plain_output = run_pdftotext(pdf)
    pages = parse_pages(bbox_output)
    plain_pages = split_plain_pages(plain_output)

    findings = []
    findings += find_unresolved_refs(plain_pages)
    findings += find_text_overlaps(pages, overlap_threshold)
    findings += find_margin_overflows(pages, margin_tolerance)
    findings.sort(key=lambda f: (f["page"], f["type"]))

    return {
        "verdict": "PASS" if not findings else "BLOCKED",
        "pdf": str(pdf),
        "pages": len(pages),
        "error_count": len(findings),
        "findings": findings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("pdf", type=Path, nargs="?", default=Path("output/pdf/paper.pdf"))
    parser.add_argument("--overlap-threshold", type=float, default=MIN_OVERLAP_FRACTION,
                         help="fraction of the smaller word's area that must be covered "
                              "before two words count as overlapping (default: %(default)s)")
    parser.add_argument("--margin-tolerance", type=float, default=MIN_MARGIN_TOLERANCE,
                         help="points of slack beyond the document's own established "
                              "left/right text column before a word is flagged "
                              "(default: %(default)s)")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    require_pdftotext()
    if not args.pdf.exists():
        print(f"PDF not found: {args.pdf}", file=sys.stderr)
        return 2

    result = check(args.pdf, args.overlap_threshold, args.margin_tolerance)

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"{result['verdict']}: {result['pdf']} — {result['pages']} page(s) checked; "
              f"{result['error_count']} error(s)")
        for f in result["findings"]:
            print(f"  ERROR     page {f['page']:<3} {f['type']}: {f['detail']}")
    return 1 if result["verdict"] == "BLOCKED" else 0


if __name__ == "__main__":
    raise SystemExit(main())
