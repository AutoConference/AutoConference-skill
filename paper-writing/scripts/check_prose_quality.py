#!/usr/bin/env python3
"""Deterministic prose gate for LaTeX manuscripts.

Implements the measurable limits in `references/prose-rules.md`. LaTeX-aware:
math, floats, verbatim, citation keys, labels, and commands are removed before
any pattern is counted, so booktabs rules and hyphenated identifiers are never
mistaken for authored punctuation.

Read-only. Never edits the manuscript.

    python3 scripts/check_prose_quality.py paper/
    python3 scripts/check_prose_quality.py paper/sections/01_introduction.tex --scope section
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

OPENING_FILLER = [
    r"\bit is important to note that\b",
    r"\bit is worth (?:noting|mentioning) that\b",
    r"\bit should be (?:noted|emphasized) that\b",
    r"\bwe would like to (?:note|emphasize|highlight) that\b",
    r"\bin order to\b",
    r"\bin the realm of\b",
    r"\bwhen it comes to\b",
    r"\bdue to the fact that\b",
    r"\bat the present time\b",
    r"\bin light of the fact that\b",
    r"\bwe now turn (?:our attention )?to\b",
    r"\bthis section (?:will )?discuss(?:es)?\b",
    r"\bit goes without saying that\b",
    r"\bas a matter of fact\b",
]

HYPE_TERMS = (
    "significant", "significantly", "substantial", "substantially", "dramatically",
    "powerful", "novel", "groundbreaking", "cutting-edge", "comprehensive", "robust",
    "pivotal", "crucial", "seamless", "holistic", "delve", "tapestry", "landscape",
    "underscore", "showcase", "leverage", "paradigm", "cornerstone", "intricate",
    "multifaceted", "nuanced", "obviously", "clearly",
)

NARRATION = [
    (r"\bthis paper (?:proposes|presents|introduces|argues|shows)\b", "third-person manuscript narration"),
    (r"\bthe authors\b", "third-person manuscript narration"),
    (r"\bthe reviewers?\b", "reviewer simulation"),
    (r"\bwe do not (?:claim|address|consider)\b", "instruction confession"),
    (r"\b(?:confirmed|approved|publication-ready|verified) (?:version|configuration|method)\b",
     "internal process status in manuscript prose"),
    (r"\b(?:readiness gate|evidence gate|agent log|autonomous agent)\b",
     "internal process language in manuscript prose"),
    (r"\bfurther research is needed\b", "generic caveat outside Limitations"),
]

FORMULAIC = {
    "not_only_but_also": r"\bnot only\b.{0,140}\bbut also\b",
    "first_second_third": r"\bfirst(?:ly)?\b.{0,300}\bsecond(?:ly)?\b.{0,300}\bthird(?:ly)?\b",
}

EM_DASH_LIMIT = {"paper": 3, "section": 0, "paragraph": 0}
SEMICOLONS_PER_1000 = 5.0   # the exemplar itself runs 4.8 in one section
ABSTRACT_NUMERIC_DENSITY = 0.30
# The exemplar itself carries a handful of 50-65 word sentences, so this is an
# advisory prompt to reread, not a defect.
LONG_SENTENCE_WORDS = 50


# Removed blocks become a sentence boundary, not a gap. Otherwise the lead-in
# sentence before a display merges with the `where` clause after it and every
# narrated equation looks like one 60-word sentence.
BREAK = " . "
BLOCK_ENVS = ("equation", "align", "gather", "tikzpicture", "axis", "verbatim",
              "lstlisting", "tabular", "NiceTabular", "table", "minipage",
              "figure", "protocolbox")


def to_prose(text: str) -> str:
    """Strip LaTeX down to authored prose."""
    text = re.sub(r"(?<!\\)%.*", "", text)
    # Acknowledgments are funding and institutional boilerplate, not authored
    # argument. Scanning them produces false narration and hype hits.
    text = re.split(r"\\section\*\{\s*Acknowledg", text)[0]
    for env in BLOCK_ENVS:
        text = re.sub(rf"\\begin\{{{env}\*?\}}.*?\\end\{{{env}\*?\}}", BREAK, text, flags=re.S)
    text = re.sub(r"\$\$.*?\$\$", " ", text, flags=re.S)
    text = re.sub(r"\$[^$]*\$", " ", text)
    text = re.sub(r"\\\[.*?\\\]", BREAK, text, flags=re.S)
    text = re.sub(r"\\(?:label|ref|Cref|cref|eqref|cite[a-z]*|input|includegraphics|"
                  r"usepackage|documentclass|bibliography[a-z]*|definecolor|rowcolor|"
                  r"colorbox|resizebox|scalebox|setlength|vspace|hspace|slot|url|href)"
                  r"\s*(?:\[[^\]]*\])?(?:\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\})*", " ", text)
    # headings keep their words but end a sentence
    text = re.sub(r"\\(?:section|subsection|subsubsection|paragraph)\*?\s*\{([^{}]*)\}",
                  r"\1" + BREAK, text)
    text = re.sub(r"\\(?:textbf|textit|emph|underline|texttt|textsc|caption)"
                  r"\*?\s*\{", " ", text)
    text = re.sub(r"\\[A-Za-z@]+\*?", " ", text)
    text = text.replace("{", " ").replace("}", " ")
    return text


def words(text: str) -> list[str]:
    return re.findall(r"[A-Za-z]+(?:[-'][A-Za-z]+)*", text)


def sentences(text: str) -> list[str]:
    flat = re.sub(r"\s+", " ", text)
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", flat) if len(words(s)) >= 3]


GENERIC_BODIES = {
    "dataset", "datasets", "model", "models", "method", "methods", "baseline", "baselines",
    "condition", "conditions", "benchmark", "benchmarks", "metric", "metrics", "task", "tasks",
    "seed", "seeds", "split", "splits", "trial", "trials", "run", "runs", "network", "networks",
    "feature", "features", "image", "images", "video", "videos", "token", "tokens", "query",
    "queries", "sample", "samples", "accuracy", "error", "loss", "score", "scores", "setting",
    "settings", "experiment", "experiments", "evaluation", "training", "inference",
}
SKIPPED_GENERIC: dict[str, str] = {}


def macro_terms(paper_dir: Path) -> dict[str, str]:
    """Canonical terms that must be written through a macro (the banana rule).

    A macro whose body is an ordinary English word ("dataset") would make the
    hand-typed-term check fire on every ordinary sentence; prose-rules.md says
    not to define such macros. Those bodies are skipped here and reported once
    at the end, rather than as dozens of warnings the writer then works around."""
    macros = paper_dir / "macros.tex"
    terms: dict[str, str] = {}
    if not macros.exists():
        return terms
    for name, body in re.findall(r"\\newcommand\{\\([A-Za-z]+)\}\{([^{}]*)\}",
                                 macros.read_text(encoding="utf-8")):
        plain = re.sub(r"\\[A-Za-z]+\s*", "", body).strip()
        if len(plain) >= 4 and re.fullmatch(r"[A-Za-z][A-Za-z0-9 .\-]*", plain):
            if plain.lower() in GENERIC_BODIES:
                SKIPPED_GENERIC[plain] = name
                continue
            terms[plain] = name
    return terms


def inspect(text: str, scope: str, name: str, terms: dict[str, str]) -> list[dict]:
    prose = to_prose(text)
    issues: list[dict] = []

    def add(sev, code, message, extra=None):
        item = {"severity": sev, "code": code, "file": name, "message": message}
        if extra:
            item.update(extra)
        issues.append(item)

    total = len(words(prose))

    em = prose.count("\u2014") + len(re.findall(r"(?<!-)---(?!-)", prose))
    limit = EM_DASH_LIMIT[scope]
    if em > limit:
        add("error", "em_dash_limit", f"{em} em dashes in authored prose; {scope} limit is {limit}")

    for pattern in OPENING_FILLER:
        for m in re.finditer(pattern, prose, flags=re.I):
            add("error", "opening_filler",
                f"throat-clearing phrase '{m.group(0).strip()}'; start with the scientific subject")

    # A hype term is a defect only when nothing nearby measures it. "improves
    # substantially" is a claim; "improves substantially, by 9.4 points" is a
    # result, and flagging the second is noise.
    hype = {}
    # "novel class", "robust statistics", "significant figures": established
    # technical phrases, not claims about this paper.
    domain_phrases = re.compile(
        r"\b(?:novel (?:class|classes|category|categories|object|objects|view|views|concept|concepts)"
        r"|robust (?:statistic|statistics|estimator|estimators|regression|optimization)"
        r"|significant (?:figure|figures|digit|digits)"
        r"|comprehensive (?:survey|benchmark))\b", re.I)
    for sentence in sentences(prose):
        if re.search(r"\d", sentence):
            continue
        stripped = domain_phrases.sub(" ", sentence)
        for term in HYPE_TERMS:
            if re.search(rf"\b{re.escape(term)}\b", stripped, flags=re.I):
                hype[term] = hype.get(term, 0) + 1
    if hype:
        add("warning", "hype_terms",
            "these appear in sentences that state no measurement; give the effect "
            "and its scope, or cut the word", {"terms": hype})

    for pattern, label in NARRATION:
        for m in re.finditer(pattern, prose, flags=re.I):
            add("error", "narration", f"{label}: '{m.group(0).strip()}'")

    for label, pattern in FORMULAIC.items():
        n = len(re.findall(pattern, prose, flags=re.I | re.S))
        if n:
            add("warning", "formulaic_structure",
                f"{label} appears {n} time(s); use the number of items the evidence supports")

    hand_typed = {}
    for plain, macro in terms.items():
        n = len(re.findall(rf"(?<![\\A-Za-z-]){re.escape(plain)}(?![A-Za-z-])", prose))
        if n:
            hand_typed[plain] = {"count": n, "macro": f"\\{macro}"}
    if hand_typed:
        add("warning", "hand_typed_term",
            "canonical terms written by hand instead of through their macro", {"terms": hand_typed})

    lengths = [len(words(s)) for s in sentences(prose)]
    runs = []
    for i in range(max(0, len(lengths) - 4)):
        window = lengths[i:i + 5]
        if len(window) == 5 and max(window) - min(window) <= 5:
            runs.append({"sentences": [i + 1, i + 5], "words": window})
    if runs:
        add("warning", "uniform_sentence_run",
            f"{len(runs)} run(s) of five sentences within a 5-word band; vary the rhythm",
            {"runs": runs[:3]})

    semis = prose.count(";")
    rate = (semis * 1000 / total) if total else 0.0
    # A rate over a handful of words is noise, not a pattern.
    if total >= 250 and rate > SEMICOLONS_PER_1000:
        add("advisory", "semicolon_density",
            f"{semis} semicolons, {rate:.1f} per 1000 words (limit {SEMICOLONS_PER_1000})")

    if "abstract" in name:
        tokens = prose.split()
        numeric = sum(1 for t in tokens if re.search(r"\d", t))
        if tokens and numeric / len(tokens) > ABSTRACT_NUMERIC_DENSITY:
            add("error", "abstract_numeric_density",
                f"{numeric}/{len(tokens)} tokens carry digits; the abstract must lead with the "
                "contribution, not the results table")

    for s in sentences(prose):
        n = len(words(s))
        if n > LONG_SENTENCE_WORDS:
            add("advisory", "long_sentence", f"{n}-word sentence; consider splitting it",
                {"text": s[:110] + ("..." if len(s) > 110 else "")})

    return issues


XSPACE_PLURAL = re.compile(r"\\([A-Za-z]+)\s+(s|es)\b")


def xspace_plurals(paper_dir: Path) -> list[dict]:
    r"""Macros pluralised by writing `\macro s`.

    Every canonical term in macros.tex ends in \xspace, which inserts a space
    before a following letter -- so `\condition s` renders as "dataset s" and
    `\condition{}s` does too. It is invisible to every other gate: it is not a
    margin overflow, not an overlap, and the macro bodies are ordinary English
    words that the hand-typed-term check deliberately exempts. A reader found
    it on page after page of a finished draft.
    """
    macros = paper_dir / "macros.tex"
    if not macros.exists():
        return []
    names = set(re.findall(r"\\newcommand\{\\([A-Za-z]+)\}\{[^{}]*\\xspace\s*\}",
                           macros.read_text(encoding="utf-8")))
    if not names:
        return []
    out = []
    for path in collect(paper_dir):
        src = re.sub(r"(?<!\\)%.*", "", path.read_text(encoding="utf-8"))
        for m in XSPACE_PLURAL.finditer(src):
            if m.group(1) not in names:
                continue
            out.append({"severity": "error", "code": "xspace_plural",
                        "file": str(path.relative_to(paper_dir.parent)),
                        "message": f"\\{m.group(1)} {m.group(2)} renders as a word with a space "
                                   f"before the '{m.group(2)}' -- \\xspace puts one there. Write the "
                                   "plural as literal text, or give it its own macro."})
    return out


def collect(target: Path) -> list[Path]:
    if target.is_file():
        return [target]
    return sorted(p for p in target.rglob("*.tex")
                  if "build" not in p.parts and "data" not in p.parts
                  and p.name not in {"preamble.tex", "preamble-layout.tex", "design.tex", "macros.tex"}
                  and not p.name.endswith(".sty"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("target", nargs="?", default="paper", help="a .tex file or a paper directory")
    parser.add_argument("--scope", choices=("paper", "section", "paragraph"), default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    target = Path(args.target).resolve()
    if not target.exists():
        print(f"not found: {target}", file=sys.stderr)
        return 2

    scope = args.scope or ("paper" if target.is_dir() else "section")
    paper_dir = target if target.is_dir() else target.parent.parent
    terms = macro_terms(paper_dir)

    files = collect(target)
    combined = "\n\n".join(p.read_text(encoding="utf-8") for p in files)
    issues: list[dict] = []
    if SKIPPED_GENERIC:
        issues.append({"severity": "advisory", "code": "generic_macro_body", "file": "macros.tex",
                       "message": "not checked as canonical terms because the body is an ordinary word "
                                  "(prose-rules.md: a macro names a distinctive object): "
                                  + ", ".join(f"\\{v} = '{k}'" for k, v in SKIPPED_GENERIC.items())})
    for path in files:
        rel = str(path.relative_to(paper_dir.parent)) if paper_dir.parent in path.parents else path.name
        issues += inspect(path.read_text(encoding="utf-8"), "section", rel, terms)
    if target.is_dir():
        issues += xspace_plurals(paper_dir)

    # em dashes are budgeted across the whole paper, not per file
    if scope == "paper":
        issues = [i for i in issues if i["code"] != "em_dash_limit"]
        prose = to_prose(combined)
        em = prose.count("\u2014") + len(re.findall(r"(?<!-)---(?!-)", prose))
        if em > EM_DASH_LIMIT["paper"]:
            issues.insert(0, {"severity": "error", "code": "em_dash_limit", "file": str(target),
                              "message": f"{em} em dashes across the manuscript; paper limit is "
                                         f"{EM_DASH_LIMIT['paper']}, zero preferred"})

    blocking = sum(1 for i in issues if i["severity"] == "error")
    result = {
        "verdict": "PASS" if blocking == 0 else "BLOCKED",
        "scope": scope,
        "files": len(files),
        "word_count": len(words(to_prose(combined))),
        "error_count": blocking,
        "issue_count": len(issues),
        "issues": issues,
    }

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"{result['verdict']}: {result['word_count']} prose words across {len(files)} file(s); "
              f"{blocking} error(s), {len(issues)} issue(s)")
        order = {"error": 0, "warning": 1, "advisory": 2}
        for item in sorted(issues, key=lambda i: order[i["severity"]]):
            print(f"  {item['severity'].upper():9s} {item['code']}: {item['message']} [{item['file']}]")

    return 1 if blocking else 0


if __name__ == "__main__":
    raise SystemExit(main())
