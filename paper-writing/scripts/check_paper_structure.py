#!/usr/bin/env python3
"""Deterministic layout gate for the executable paper template.

Verifies a LaTeX manuscript against the contract in
`references/paper-writing-template.md`: section order, per-section word
budgets, equation narration, table and figure grammar, placeholder residue,
cross-reference closure, and bibliography hygiene.

Read-only. Never edits the manuscript.

    python3 scripts/check_paper_structure.py
    python3 scripts/check_paper_structure.py --submission --json
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import shutil
import subprocess
import sys
from pathlib import Path

# --------------------------------------------------------------------------
# Contract, measured from arXiv:2506.21656v3 (see references/paper-writing-template.md §1)
# --------------------------------------------------------------------------

SECTION_ORDER = ["Introduction", "Related Work", "Method", "Experiments", "Conclusion"]

WORD_BUDGET = {
    # file stem            (low, high, exemplar)
    "00_abstract": (140, 190, 154),
    "01_introduction": (420, 650, 495),
    "02_related_work": (420, 650, 503),
    "03_method": (1300, 2100, 1724),
    "04_experiments": (600, 1000, 688),
    "05_conclusion": (180, 320, 224),
    "06_appendix": (1500, 12000, 3376),
}
MAIN_BODY_BUDGET = (3100, 4300)
MIN_METHOD_EQUATIONS = 4
MIN_MAIN_BODY_CITATIONS = 40

FORBIDDEN = {
    r"\bTBD\b": "unfilled value marker",
    r"DATA SLOT": "placeholder visual",
    r"MANIFEST DATA SLOT": "placeholder visual",
    r"PAIRED DATA SLOT": "placeholder visual",
    r"\bPLACEHOLDER\b": "placeholder marker",
    r"\\placeholder\b": "deprecated placeholder macro; use \\slot",
    r"\bTODO\b|\bFIXME\b|\bXXX\b": "development marker",
    r"Lorem ipsum": "filler text",
    r"example\.(?:edu|org|com)": "example address",
    r"First Author|Second Author|Senior Author": "template author name",
    r"Primary Institution|Collaborating Institution": "template affiliation",
    r"\bFigure omitted\b|\bComing soon\b": "empty float",
}

CAPTION_LEAD = re.compile(r"\\caption\{\s*%?\s*\\textbf\{")

# --------------------------------------------------------------------------
# The design family (references/design-axes.md). A paper assembled by
# scripts/design_paper.py carries its drawn design in paper.json; every rule
# below that used to be one exemplar's choice is read from that draw instead.
# A paper without a design (the legacy example/ and specimens) keeps the
# original single-exemplar rules, so nothing that passed before regresses.
# --------------------------------------------------------------------------

def load_design(paper: Path) -> dict | None:
    cfg = paper.parent / "paper.json"
    if not cfg.exists():
        return None
    try:
        return json.loads(cfg.read_text(encoding="utf-8")).get("design")
    except json.JSONDecodeError:
        return None


VRULE_GRAMMARS = {"delta-rows", "rank-colors", "grouped-rules", "naive-vs-ours"}
SECTION_ALIASES = {"Method": ("Method", "Methodology", "Approach"),
                   "Related Work": ("Related Work", "Related Works", "Background"),
                   "Experiments": ("Experiments", "Experimental Results", "Evaluation"),
                   "Ablation Study": ("Ablation Study", "Ablations", "Ablation Studies")}


def expected_sections(design: dict | None) -> list[str]:
    if design is None:
        return list(SECTION_ORDER)
    # Related Work is expected in every organization: `related=appendix` keeps a
    # short main-body stub pointing at the full appendix section (P4, P6), so the
    # section heading is there either way -- only its length differs, and that is
    # the budget's business, not the section order's.
    order = ["Introduction", "Related Work", "Method", "Experiments"]
    if design.get("experiments") == "separate-ablation-section":
        order.append("Ablation Study")
    order.append("Conclusion")
    return order


def section_matches(seen: str, wanted: str) -> bool:
    return seen.lower() in {a.lower() for a in SECTION_ALIASES.get(wanted, (wanted,))}


# --------------------------------------------------------------------------
# LaTeX -> prose
# --------------------------------------------------------------------------

def strip_comments(text: str) -> str:
    return re.sub(r"(?<!\\)%.*", "", text)


def to_prose(text: str) -> str:
    """Reduce LaTeX to countable authored prose."""
    text = strip_comments(text)
    for env in ("equation", "align", "gather", "tikzpicture", "axis", "verbatim",
                "lstlisting", "tabular", "NiceTabular", "table", "figure"):
        text = re.sub(rf"\\begin\{{{env}\*?\}}.*?\\end\{{{env}\*?\}}", " ", text, flags=re.S)
    text = re.sub(r"\$\$.*?\$\$", " ", text, flags=re.S)
    text = re.sub(r"\$[^$]*\$", " ", text)
    text = re.sub(r"\\\[.*?\\\]", " ", text, flags=re.S)
    # commands whose arguments are not prose
    text = re.sub(r"\\(?:label|ref|Cref|cref|eqref|cite[a-z]*|input|includegraphics|"
                  r"usepackage|documentclass|bibliography[a-z]*|definecolor|rowcolor|"
                  r"colorbox|tightcolorbox|resizebox|scalebox|fontsize|selectfont|"
                  r"setlength|vspace|hspace|newcommand|renewcommand|slot)"
                  r"\s*(?:\[[^\]]*\])?(?:\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\})*", " ", text)
    # keep the argument of formatting commands
    text = re.sub(r"\\(?:textbf|textit|emph|underline|texttt|textsc|section|subsection|"
                  r"subsubsection|caption|paragraph)\*?\s*\{", " ", text)
    text = re.sub(r"\\[A-Za-z@]+\*?", " ", text)
    text = text.replace("{", " ").replace("}", " ").replace("&", " ")
    text = re.sub(r"[~\\]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def word_count(text: str) -> int:
    return len(re.findall(r"[A-Za-z]+(?:[-'][A-Za-z]+)*", to_prose(text)))


# --------------------------------------------------------------------------
# Checker
# --------------------------------------------------------------------------

class Report:
    def __init__(self) -> None:
        self.items: list[dict] = []

    def add(self, severity: str, code: str, message: str, where: str = "") -> None:
        self.items.append({"severity": severity, "code": code, "message": message, "where": where})

    def error(self, code, message, where=""):
        self.add("error", code, message, where)

    def warn(self, code, message, where=""):
        self.add("warning", code, message, where)

    def note(self, code, message, where=""):
        self.add("advisory", code, message, where)

    @property
    def blocking(self) -> int:
        return sum(1 for i in self.items if i["severity"] == "error")


NON_MANUSCRIPT = {"preamble.tex", "preamble-layout.tex", "design.tex", "macros.tex"}


def tex_files(paper: Path) -> list[Path]:
    """Manuscript sources: everything except the build tree, the preambles,
    the generated design switches, and the terminology macros -- none of
    which carry a float, a label, or a slot that renders."""
    return sorted(p for p in paper.rglob("*.tex")
                  if "build" not in p.parts and p.name not in NON_MANUSCRIPT)


def check_layout(paper: Path, rep: Report, design: dict | None = None) -> dict:
    main = paper / "main.tex"
    if not main.exists():
        rep.error("missing_main", f"{main} not found")
        return {}
    main_src = strip_comments(main.read_text(encoding="utf-8"))

    inputs = re.findall(r"\\input\{(sections/[^}]+)\}", main_src)
    if not inputs:
        rep.error("no_sections", "main.tex inputs no section files")

    titles: list[str] = []
    for rel in inputs:
        if "appendix" in rel:
            continue
        path = paper / (rel if rel.endswith(".tex") else rel + ".tex")
        if not path.exists():
            guarded = re.search(r"\\IfFileExists\{" + re.escape(rel) + r"(?:\.tex)?\}", main_src)
            if not guarded:
                rep.error("missing_section", f"main.tex inputs a file that does not exist", rel)
            continue
        titles += re.findall(r"\\section\{([^}]*)\}", strip_comments(path.read_text(encoding="utf-8")))

    normalized = [re.sub(r"\\[A-Za-z]+\s*", "", t).strip() for t in titles]
    wanted = expected_sections(design)
    got = normalized[:len(wanted)]
    if len(got) != len(wanted) or any(not section_matches(g, w) for g, w in zip(got, wanted)):
        rep.error("section_order",
                  f"section order is {normalized[:len(wanted)] or '[]'}; this design requires {wanted}",
                  "main.tex")

    wants_appendix = design is None or design.get("appendix", "lettered") != "none"
    if wants_appendix and "\\appendix" not in main_src:
        appendix = paper / "sections/06_appendix.tex"
        if not (appendix.exists() and "\\appendix" in appendix.read_text(encoding="utf-8")):
            rep.warn("no_appendix", "no \\appendix found; this design expects an appendix")


    return {"inputs": inputs, "sections": normalized}


def check_budgets(paper: Path, rep: Report, submission: bool, design: dict | None = None) -> dict:
    incomplete = rep.error if submission else rep.warn
    measured: dict[str, int] = {}
    main_body = 0
    budget = dict(WORD_BUDGET)
    body_budget = MAIN_BODY_BUDGET
    if design:
        b = design.get("budgets", {})
        for stem in list(budget):
            if stem in b:
                budget[stem] = (b[stem][0], b[stem][1], None)
        if design.get("related") == "appendix":
            budget["02_related_work"] = (0, budget["02_related_work"][1], None)
        if "_main_body" in b:
            body_budget = tuple(b["_main_body"])
    for stem, (low, high, exemplar) in budget.items():
        path = paper / "sections" / f"{stem}.tex"
        if not path.exists():
            rep.error("missing_section_file", f"section file not found", f"sections/{stem}.tex")
            continue
        n = word_count(path.read_text(encoding="utf-8"))
        if stem == "04_experiments" and (paper / "sections/04b_ablation.tex").exists():
            n += word_count((paper / "sections/04b_ablation.tex").read_text(encoding="utf-8"))
        lim = paper / "blocks/limitations.tex"
        if lim.exists() and design:
            where = {"appendix": "06_appendix", "conclusion-paragraph": "05_conclusion"}.get(design.get("limitations"))
            if where == stem:
                n += word_count(unwrap_macro_blocks(lim.read_text(encoding="utf-8")))
        if stem == "03_method" and (paper / "blocks/method_open.tex").exists():
            # the drawn method opening is \input at the top of the section and
            # is part of it: its prose (and, for `preliminaries`, its displays)
            # count toward the section
            n += word_count((paper / "blocks/method_open.tex").read_text(encoding="utf-8"))
        measured[stem] = n
        if stem != "06_appendix" and stem != "00_abstract":
            main_body += n
        if stem == "06_appendix" and low == 0:
            continue
        if n < low:
            incomplete("under_budget",
                      f"{n} words; the envelope for this design is {low}-{high}"
                      f"{f' (exemplar {exemplar})' if exemplar else ''}. "
                      "A short section is a missing argument move, not a style choice.",
                      f"sections/{stem}.tex")
        elif n > high:
            rep.warn("over_budget",
                     f"{n} words; the envelope for this design is {low}-{high}"
                     f"{f' (exemplar {exemplar})' if exemplar else ''}. "
                     "Move detail to the appendix.",
                     f"sections/{stem}.tex")
    lim = paper / "blocks/limitations.tex"
    if design and design.get("limitations") == "own-section" and lim.exists():
        # It renders after the conclusion as its own unnumbered section, so it is
        # main-body prose. The `appendix` and `conclusion-paragraph` placements
        # are already folded into their host section above; this one had no host
        # and was silently counted nowhere, shrinking the measured main body by
        # its whole length and pushing the writer to pad another section.
        own = word_count(unwrap_macro_blocks(lim.read_text(encoding="utf-8")))
        measured["_limitations_own_section"] = own
        main_body += own
    if main_body:
        low, high = body_budget
        # Same asymmetry as the per-section check just above, and deliberately
        # so: running short of the envelope means the paper is missing
        # argument moves across sections, not a style choice, so submission
        # mode refuses it exactly as it refuses a single under-budget section.
        # Running over is normally a fixable trim (move detail to the
        # appendix) and is bounded by the hard page-count gate in check_pdf,
        # so it stays a warning in every mode.
        if main_body < low:
            incomplete("main_body_under_budget",
                     f"main body is {main_body} words; contract envelope is {low}-{high}. "
                     "Short sections compound into a main body missing argument moves.")
        elif main_body > high:
            rep.warn("main_body_over_budget",
                     f"main body is {main_body} words; contract envelope is {low}-{high}")
    measured["_main_body"] = main_body
    return measured


def check_abstract(paper: Path, rep: Report) -> None:
    path = paper / "sections/00_abstract.tex"
    if not path.exists():
        return
    raw = strip_comments(path.read_text(encoding="utf-8"))
    if re.search(r"\\cite[a-z]*\{", raw):
        rep.error("abstract_citation", "the abstract must not cite", "sections/00_abstract.tex")
    if re.search(r"\\begin\{(?:equation|align)", raw):
        rep.error("abstract_display", "the abstract must not contain display math", "sections/00_abstract.tex")
    # Numeric density in the abstract is check_prose_quality.py's rule and is
    # raised there as an error. It was also computed here, with the same
    # threshold and a different severity, so one defect arrived twice wearing
    # two different verdicts. The prose gate owns it; this one owns structure.
    if len(re.findall(r"\n\s*\n", raw.strip())) > 0:
        rep.warn("abstract_paragraphs", "the abstract must be a single paragraph", "sections/00_abstract.tex")


def check_equations(paper: Path, rep: Report, submission: bool, design: dict | None = None) -> dict:
    incomplete = rep.error if submission else rep.warn
    floor = MIN_METHOD_EQUATIONS if design is None else int(design.get("equation_floor", MIN_METHOD_EQUATIONS))
    method = paper / "sections/03_method.tex"
    stats = {"method_equations": 0, "unlabeled": 0, "unnarrated": 0, "adjacent": 0}
    if not method.exists():
        return stats
    src = strip_comments(method.read_text(encoding="utf-8"))
    opener = paper / "blocks/method_open.tex"
    if opener.exists():
        src = strip_comments(opener.read_text(encoding="utf-8")) + "\n" + src
    blocks = list(re.finditer(r"\\begin\{equation\*?\}(.*?)\\end\{equation\*?\}", src, flags=re.S))
    stats["method_equations"] = len(blocks)
    if len(blocks) < floor:
        incomplete("too_few_equations",
                  f"{len(blocks)} numbered equations in the method; this design's register "
                  f"({(design or {}).get('equations', 'dense')}) requires at least {floor}",
                  "sections/03_method.tex")
    if design and design.get("equations") == "sectioned":
        joined = src + "\n" + "\n".join(
            strip_comments(p.read_text(encoding="utf-8")) for p in tex_files(paper) if "blocks" in p.parts)
        if "\\begin{algorithm}" not in joined:
            rep.warn("no_algorithm_float",
                     "the sectioned equation register expects an algorithm float in the method "
                     "(\\input{blocks/algorithm})", "sections/03_method.tex")
    for m in blocks:
        body = m.group(1)
        line = src.count("\n", 0, m.start()) + 1
        if "\\label{" not in body and "*" not in src[m.start():m.start() + 20]:
            stats["unlabeled"] += 1
            rep.warn("equation_unlabeled",
                     "numbered equation has no \\label; number a display only when prose "
                     "refers to it",
                      f"sections/03_method.tex:{line}")
        trailer = src[m.end():m.end() + 320].lstrip()
        if not re.match(r"(?i)\s*(?:where|here|with|in which)\b", trailer):
            stats["unnarrated"] += 1
            rep.warn("equation_unnarrated",
                     "no 'where'/'here' narration sentence follows the display; every symbol "
                     "must be defined immediately after its equation",
                     f"sections/03_method.tex:{line}")
        if re.match(r"\s*\\begin\{(?:equation|align)", trailer):
            stats["adjacent"] += 1
            rep.warn("equations_adjacent", "two displays with no prose between them",
                     f"sections/03_method.tex:{line}")
    return stats


def is_numeric_cell(cell: str) -> bool:
    r"""True when a cell carries data rather than a label.

    A row-label column holds things like ``Gemini 2.0 Flash`` and
    ``InternVL2.5-78B``; scanning their digits against a data column's decimals
    is a false positive. A data cell reduces to digits and arithmetic
    punctuation once LaTeX formatting is removed.

    `[` and `]` are allowed alongside the plain-±-glyph case: table-grammar.md's
    uncertainty convention is ``0.912 [0.884, 0.940]`` (a `lo, hi` pair, since
    the evidence is an empirical range or a Wilson interval, not a symmetric
    half-width -- see references/table-grammar.md "Reporting uncertainty").
    Without this, a bracketed cell fails this predicate entirely, which does
    not just skip the per-column precision check -- it also drops the cell's
    numbers out of `evidence_numbers()`, so a headline result quoted in the
    abstract could be reclassified as "unsupported" the moment its table cell
    grew an interval. That is a self-inflicted gate failure, not a real one.
    """
    text = re.sub(r"\\[A-Za-z@]+\*?", " ", cell)
    text = re.sub(r"[{}$~]", " ", text).strip()
    if not re.search(r"\d", text):
        return False
    return re.fullmatch(r"[\d\s.,%/+\-\u00b1\[\]]*", text) is not None


TABULAR_ENV = re.compile(r"\\(begin|end)\{((?:Nice)?[Tt]abular)\*?\}")


def tabular_bodies_with_pos(block: str) -> list[tuple[int, str]]:
    """(start offset, body) for the outermost tabular environments, nesting-aware.

    A non-greedy regex stops at the first \\end{tabular}, which for a table
    whose header uses a nested \\begin{tabular}{c}...\\end{tabular} for a
    two-line column label is the header's end, not the table's. Everything
    after it, meaning the entire numeric body, then goes unchecked. Match by
    depth instead.
    """
    bodies, depth, start = [], 0, None
    for m in TABULAR_ENV.finditer(block):
        if m.group(1) == "begin":
            if depth == 0:
                start = m.end()
            depth += 1
        else:
            depth -= 1
            if depth == 0 and start is not None:
                bodies.append((start, block[start:m.start()]))
                start = None
    return bodies


def tabular_bodies(block: str) -> list[str]:
    """Bodies of the outermost tabular environments. See tabular_bodies_with_pos."""
    return [body for _, body in tabular_bodies_with_pos(block)]


def numeric_columns(body: str) -> list[list[str]]:
    r"""Return per-column numeric cell lists from a tabular BODY.

    Header rows carry column labels that are often numeric with a different
    precision than the data (``10\%``, ``$\lambda$=0.2``). Analysing them
    against the body is a false positive, so everything above the first
    \midrule is dropped.
    """
    cut = re.search(r"\\midrule(?:\[[^\]]*\])?", body)
    if cut:
        body = body[cut.end():]
    else:
        # No booktabs header rule, which is its own error. Drop the first row
        # anyway so a header label is never compared against the data.
        body = body.split(r"\\", 1)[-1]
    rows: list[list[str]] = []
    for raw_row in body.split(r"\\"):
        row = raw_row
        for cmd in ("toprule", "midrule", "bottomrule", "cmidrule", "hline"):
            row = re.sub(rf"\\{cmd}(?:\[[^\]]*\])?(?:\([^)]*\))?(?:\{{[^}}]*\}})?", " ", row)
        row = re.sub(r"\\rowcolor\{[^}]*\}", " ", row)
        if "&" not in row:
            continue
        rows.append([c.strip() for c in re.split(r"(?<!\\)&", row)])
    width = max((len(r) for r in rows), default=0)
    return [[r[i] for r in rows if i < len(r)] for i in range(width)]


def check_tables(paper: Path, rep: Report, design: dict | None = None) -> dict:
    stats = {"tables": 0}
    caption_below = bool(design and design.get("table_caption") == "below")
    vrules_ok = bool(design and (design.get("main_table") in VRULE_GRAMMARS
                                 or design.get("ablation") in VRULE_GRAMMARS))
    for path in tex_files(paper):
        src = strip_comments(path.read_text(encoding="utf-8"))
        rel = str(path.relative_to(paper.parent))
        for m in re.finditer(r"\\begin\{(?:table\*?|acwidetable)\}(?:\[[^\]]*\])?(.*?)\\end\{(?:table\*?|acwidetable)\}", src, flags=re.S):
            stats["tables"] += 1
            block = m.group(1)
            line = src.count("\n", 0, m.start()) + 1
            where = f"{rel}:{line}"

            cap_m = re.search(r"\\caption\s*\{", block)
            cap = cap_m.start() if cap_m else -1
            tab = min([i for i in (block.find("\\begin{tabular}"),
                                   block.find("\\begin{NiceTabular}")) if i >= 0] or [-1])
            if cap < 0:
                rep.error("table_no_caption", "table has no caption", where)
            elif tab >= 0 and cap > tab and not caption_below:
                rep.error("table_caption_below", "table caption must be above the tabular", where)
            elif tab >= 0 and cap < tab and caption_below and "\\label{tab:main-results}" in block:
                rep.error("table_caption_above", "this design's table grammar (grouped-rules, P7) "
                          "places the main table's caption below the tabular", where)
            if cap >= 0 and not CAPTION_LEAD.search(block[cap:cap + 60]):
                rep.warn("table_caption_lead", "caption should open with a bold lead phrase", where)
            if "\\label{" not in block:
                rep.error("table_no_label", "table has no \\label", where)
            if "\\hline" in block:
                rep.error("table_hline", "use booktabs rules, never \\hline", where)
            for spec in re.findall(r"\\begin\{(?:Nice)?[Tt]abular\}(?:\[[^\]]*\])?\{([^}]*)\}", block):
                if "|" in spec and not vrules_ok:
                    rep.error("table_vrule", f"vertical rule in column spec '{spec}'", where)
            if re.search(r"\\begin\{table\*?\}\[H\]", src[m.start():m.start() + 30]):
                rep.error("table_placement_H", "never use [H]; let the class place floats", where)

            for body in tabular_bodies(block):
                for idx, column in enumerate(numeric_columns(body)):
                    precisions = set()
                    seen = 0
                    for cell in column:
                        if not is_numeric_cell(cell):
                            continue
                        for num in re.findall(r"-?\d+(?:\.\d+)?", cell):
                            seen += 1
                            precisions.add(len(num.split(".")[1]) if "." in num else 0)
                    if seen >= 3 and len(precisions) > 1:
                        rep.error("table_precision",
                                  f"column {idx + 1} mixes decimal precisions {sorted(precisions)}; "
                                  "every value in a column takes the same number of decimals",
                                  where)
    return stats


# --------------------------------------------------------------------------
# Bold/underline winner check (table-grammar.md golden rule 7)
#
# "Bolding an unsupported win is the single most damaging table defect
# available" (table-grammar.md, Evidence rules). This only checks the
# column-wise orientation: rows are the compared entities (methods, arms,
# configurations) and each column is one metric, which is the mandatory main-
# and secondary-results pattern (table-grammar.md patterns 1-2) and is what a
# wrongly-bolded headline number actually looks like.
#
# Pattern 3's paired ablation tables are sometimes transposed (rows are
# statistics -- "Mean", "Std." -- columns are the swept setting), and a
# column-wise comparison there would compare a mean against a standard
# deviation, which is nonsense. This check detects that orientation from the
# row labels and skips the table rather than emit a guess; the honest answer
# for a transposed ablation table is that this check cannot currently say
# anything about it, not that it is clean.
# --------------------------------------------------------------------------

DIRECTION_UP = re.compile(r"\\up\b|\\uparrow|\u2191")
DIRECTION_DOWN = re.compile(r"\\down\b|\\downarrow|\u2193")

# Column headers that name a count, a size, a spread statistic, or a relative
# contrast rather than a metric whose magnitude the table is ranking methods
# on. Matched as a substring of the lowercased, LaTeX-stripped header cell.
NONMETRIC_COLUMN_KEYWORDS = (
    "seed", "traj", "shard", "trial", "bench", "rep", "cond", "std", "range",
    "contrast", "contr", "count", "size", "epoch", "comp", "tier", "inline",
    "delta", "cap. factor", "k$",
)

# Row labels that name a statistic rather than a compared entity. A table
# where any data row's own label reads this way is the transposed pattern
# (table-grammar.md pattern 3 as actually used): skip it entirely rather than
# compare a mean against a standard deviation as if they were rival methods.
NONMETRIC_ROW_KEYWORDS = (
    "mean", "std", "average", "avg", "stdev", "standard deviation", "range",
    "variance", "spread",
)

NESTED_TABULAR_ROW_SPLIT = re.compile(
    r"\\begin\{tabular\}(?:\[[^\]]*\])?\{[^}]*\}|\\end\{tabular\}|\\\\")


def split_top_rows(text: str) -> list[str]:
    r"""Split on row-separating \\, ignoring a nested two-line-header
    tabular's own internal \\ (\begin{tabular}{c}Split\\seeds\end{tabular})."""
    depth, start, rows = 0, 0, []
    for m in NESTED_TABULAR_ROW_SPLIT.finditer(text):
        tok = m.group(0)
        if tok.startswith(r"\begin"):
            depth += 1
        elif tok.startswith(r"\end"):
            depth -= 1
        elif depth == 0:
            rows.append(text[start:m.start()])
            start = m.end()
    rows.append(text[start:])
    return rows


def header_label_cells(body: str) -> list[str]:
    """Per-column header text, aligned with numeric_columns()'s column index.

    Uses the last top-level row before the first \\midrule: a grouped-column
    header (a \\Block spanning several metrics) carries a title row above the
    per-column labels, and the labels are what identifies a column.
    """
    cut = re.search(r"\\midrule(?:\[[^\]]*\])?", body)
    if not cut:
        return []
    header = body[:cut.start()]
    for cmd in ("toprule", "midrule", "bottomrule", "cmidrule", "hline"):
        header = re.sub(rf"\\{cmd}(?:\[[^\]]*\])?(?:\([^)]*\))?(?:\{{[^}}]*\}})?", " ", header)
    rows = [r for r in split_top_rows(header) if "&" in r]
    if not rows:
        return []
    return [c.strip() for c in re.split(r"(?<!\\)&", rows[-1])]


def plain_text(cell: str) -> str:
    text = re.sub(r"\\[A-Za-z@]+\*?", " ", cell)
    text = re.sub(r"[{}$~]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def is_nonmetric_header(cell: str) -> bool:
    low = plain_text(cell).lower()
    raw_low = cell.lower()
    if "\\delta" in raw_low or "\u0394" in cell:
        return True
    return any(k in low or k in raw_low for k in NONMETRIC_COLUMN_KEYWORDS)


def looks_row_oriented(row_labels: list[str]) -> bool:
    for cell in row_labels:
        text = plain_text(cell).lower()
        if any(k in text for k in NONMETRIC_ROW_KEYWORDS):
            return True
    return False


def cell_primary_value(cell: str) -> float | None:
    """The cell's first number: the point estimate in a "0.912 [0.884, 0.940]"
    or "mean $\\pm$ std" cell. Correct either way because it always takes
    nums[0] and the convention always writes the point estimate first, before
    its interval -- never "[0.884, 0.940] 0.912"."""
    nums = re.findall(r"-?\d+(?:\.\d+)?", plain_text(cell))
    return float(nums[0]) if nums else None


def table_direction(block: str, pos: int) -> str | None:
    """up/down for the tabular body starting at POS, from its nearest
    preceding \\caption in the same float (table-grammar.md rule 8:
    direction is stated in the caption or header, once)."""
    # The caption may sit before the tabular (five grammars) or after it
    # (grouped-rules, P7). Take the nearest one in either direction.
    captions = [m.start() for m in re.finditer(r"\\caption\s*\{", block)]
    if not captions:
        return None
    nearest = min(captions, key=lambda c: abs(c - pos))
    window = block[nearest:nearest + 400]
    mu, md = DIRECTION_UP.search(window), DIRECTION_DOWN.search(window)
    if mu and (not md or mu.start() < md.start()):
        return "up"
    if md:
        return "down"
    return None


def check_table_extremes(paper: Path, rep: Report, design: dict | None = None) -> dict:
    stats = {"tables_checked": 0, "columns_checked": 0, "flagged": 0}
    row_wise_label = "\\label{tab:ablation}" if design and design.get("ablation") == "naive-vs-ours" else None
    for path in tex_files(paper):
        src = strip_comments(path.read_text(encoding="utf-8"))
        rel = str(path.relative_to(paper.parent))
        for m in re.finditer(r"\\begin\{(?:table\*?|acwidetable)\}(?:\[[^\]]*\])?(.*?)\\end\{(?:table\*?|acwidetable)\}", src, flags=re.S):
            block = m.group(1)
            line = src.count("\n", 0, m.start()) + 1
            if row_wise_label and row_wise_label in block:
                # P4's naive-vs-ours grammar reads Naive | Ours across each row;
                # a column-wise extremum is not what its bold means. Unchecked
                # by design rather than guessed at (table-grammar.md).
                continue

            for pos, body in tabular_bodies_with_pos(block):
                for cell in re.finditer(r"\\(?:textbf|best)\{[^{}]*\\(?:underline|second)\{|"
                                         r"\\(?:underline|second)\{[^{}]*\\(?:textbf|best)\{", body):
                    stats["flagged"] += 1
                    body_line = line + body.count("\n", 0, cell.start())
                    rep.error("table_bold_and_underline",
                              "a cell is both bolded and underlined; table-grammar.md rule 7 "
                              "reserves bold for the single best value and underline for the "
                              "single second-best",
                              f"{rel}:{body_line}")

                columns = numeric_columns(body)
                if not columns:
                    continue
                if looks_row_oriented(columns[0]):
                    continue
                direction = table_direction(block, pos)
                headers = header_label_cells(body)
                if direction is None and not any(DIRECTION_UP.search(h) or DIRECTION_DOWN.search(h) for h in headers):
                    continue

                row_labels = columns[0]
                for idx, column in enumerate(columns):
                    if idx == 0:
                        continue
                    header = headers[idx] if idx < len(headers) else ""
                    if is_nonmetric_header(header):
                        continue
                    # grouped-rules (P7) and rank-colors (P4) carry the arrow in
                    # each column header; a per-column arrow outranks the
                    # caption's single direction.
                    col_dir = direction
                    if DIRECTION_UP.search(header) and not DIRECTION_DOWN.search(header):
                        col_dir = "up"
                    elif DIRECTION_DOWN.search(header) and not DIRECTION_UP.search(header):
                        col_dir = "down"
                    entries = []
                    for row_idx, cell in enumerate(column):
                        # A derived summary row (secondary_results.tex's
                        # "Difference" row, table-grammar.md pattern 2) is not
                        # a rival entity; its value is a contrast, not a
                        # measurement on the metric's own scale, and belongs
                        # in the same never-compared bucket as a contrast
                        # column. Excluding it by row rather than skipping the
                        # whole table keeps the table-wide column-wise check
                        # valid for every other row.
                        label = row_labels[row_idx] if row_idx < len(row_labels) else ""
                        if any(k in plain_text(label).lower()
                               for k in ("difference", "delta", "gain", "improvement")) \
                                or "\\Delta" in label or "\\deltarow" in cell:
                            continue
                        if not is_numeric_cell(cell):
                            continue
                        value = cell_primary_value(cell)
                        if value is None:
                            continue
                        entries.append((
                            value,
                            bool(re.search(r"\\textbf\{|\\mathbf\{|\\bfseries\b|\\best\{|\\rankone\{", cell)),
                            bool(re.search(r"\\underline\{|\\second\{|\\ranktwo\{", cell)),
                        ))
                    if len(entries) < 2:
                        continue
                    stats["columns_checked"] += 1

                    if col_dir is None:
                        continue
                    reverse = col_dir == "up"
                    ordered = sorted((v for v, *_ in entries), reverse=reverse)
                    best = ordered[0]
                    rest = [v for v in ordered if v != best]
                    second = rest[0] if rest else None

                    for value, bold, underline in entries:
                        if bold and value != best:
                            stats["flagged"] += 1
                            rep.error("table_bold_not_best",
                                      f"column {idx + 1} bolds {value}, but the column's "
                                      f"best value under the declared direction ({col_dir}) "
                                      f"is {best}. Bolding an unsupported win is the single "
                                      "most damaging table defect.",
                                      f"{rel}:{line}")
                        elif underline and second is not None and value not in (best, second):
                            stats["flagged"] += 1
                            rep.error("table_underline_not_second_best",
                                      f"column {idx + 1} underlines {value} as second-best, "
                                      f"but {second} is; {value} is not in the top two under "
                                      f"the declared direction ({col_dir})",
                                      f"{rel}:{line}")
                        elif underline and value == best:
                            stats["flagged"] += 1
                            rep.warn("table_underline_is_best",
                                     f"column {idx + 1} underlines {value}, but it is the "
                                     f"column's best value, not merely second-best; bold it",
                                     f"{rel}:{line}")
                stats["tables_checked"] += 1
    return stats


def _load_icon_allowlist() -> set[str]:
    """The verified icon names, from the data file the skill ships.

    Not a literal in this source. The list is 935 names, it is generated rather
    than curated, and it is read by a writer as often as by this gate --
    references/figure-icons.verified.txt is the one copy. An earlier version
    hard-coded 79 hand-picked names here, and that list being 8% of what the
    font ships is precisely why a writer could not find a fitting glyph and
    reached for a bare box instead.

    A missing file degrades to permissive rather than failing every paper: this
    check exists to catch a typo, and it is not worth a false failure on every
    manuscript if the data file is ever lost.
    """
    f = pathlib.Path(__file__).resolve().parent.parent / "references" / "figure-icons.verified.txt"
    try:
        return {ln.strip() for ln in f.read_text(encoding="utf-8").splitlines()
                if ln.strip() and not ln.startswith("#")}
    except OSError:
        return set()


ICON_ALLOWED = _load_icon_allowlist()
# Conventional, and never drawn: \acsnow and \acflame wrap them.
ICON_FIXED = {"Snowflake", "Fire"}


def check_icons(paper: Path, rep: Report) -> dict:
    """Every icon a paper names must be one that renders.

    A name outside the list does not fail at build time in a way anyone can
    read: fontawesome5 reports `The requested icon <name> was not found` and
    halts, naming the icon but not the file, and the writer sees a LaTeX error
    where they expected a figure. Catching it here names the file and the line.
    """
    stats = {"icons": 0}
    roles = ("Input", "Model", "Mech", "Out", "Evid")
    # NOT tex_files(): that list deliberately drops design.tex, macros.tex and
    # the preambles because they carry no float, label or slot. Icon names live
    # in exactly those two -- design.tex is where a draw lands and macros.tex is
    # where a writer overrides one -- so this check scans everything.
    sources = sorted(f for f in paper.rglob("*.tex") if "build" not in f.parts)
    for path in sources:
        src = strip_comments(path.read_text(encoding="utf-8"))
        rel = str(path.relative_to(paper.parent))
        # \renewcommand{\acIconInput}{Atom}  -- a design draw or a writer override
        for m in re.finditer(r"\\(?:re)?newcommand\{\\acIcon(" + "|".join(roles) +
                             r")\}\{([A-Za-z]*)\}", src):
            stats["icons"] += 1
            role, name = m.group(1), m.group(2)
            if ICON_ALLOWED and name not in ICON_ALLOWED:
                line = src.count("\n", 0, m.start()) + 1
                rep.error("icon_unknown",
                          f"\\acIcon{role} is set to '{name}', which is not a verified "
                          f"icon; choose one from references/figure-icons.md",
                          f"{rel}:{line}")
        # \acicon{Name} / \aciconat{Colour}{Name} written literally in a block
        for m in re.finditer(r"\\acicon\{([A-Za-z]+)\}|\\aciconat\{[^}]*\}\{([A-Za-z]+)\}", src):
            name = m.group(1) or m.group(2)
            stats["icons"] += 1
            if ICON_ALLOWED and name not in ICON_ALLOWED and name not in ICON_FIXED:
                line = src.count("\n", 0, m.start()) + 1
                rep.error("icon_unknown",
                          f"'{name}' is not a verified icon; choose one from "
                          f"references/figure-icons.md",
                          f"{rel}:{line}")

    # The system figure leads every node with a glyph. A paper whose overview
    # draws none is not a style choice -- axis 15 has no plain value and all
    # five grammars carry icons -- it is a paper assembled before the icon
    # layer, or one whose figure was hand-edited back to bare boxes. Both
    # printed a diagram a reader called lifeless next to one that was not, in
    # the same batch, which is the drift this catches.
    ov = paper / "figures/method_overview.tex"
    if ov.exists():
        body = strip_comments(ov.read_text(encoding="utf-8"))
        if "\\acicon" not in body and "\\aciconat" not in body:
            rep.error("overview_no_icons",
                      "the system figure draws no icons; every overview grammar "
                      "leads its nodes with \\acicon{\\acIcon...} "
                      "(references/figure-icons.md). A pre-icon-layer paper needs "
                      "its figure ported, not left as bare boxes",
                      "figures/method_overview.tex")
    return stats


def check_figures(paper: Path, rep: Report, design: dict | None = None) -> dict:
    stats = {"figures": 0}
    for path in tex_files(paper):
        src = strip_comments(path.read_text(encoding="utf-8"))
        rel = str(path.relative_to(paper.parent))
        for m in re.finditer(r"\\begin\{(?:figure\*?|acwidefigure)\}(?:\[[^\]]*\])?(.*?)\\end\{(?:figure\*?|acwidefigure)\}", src, flags=re.S):
            stats["figures"] += 1
            block = m.group(1)
            line = src.count("\n", 0, m.start()) + 1
            where = f"{rel}:{line}"
            cap_m = re.search(r"\\caption\s*\{", block)
            cap = cap_m.start() if cap_m else -1
            # first graphic, so an \includegraphics used inside a caption
            # (an inline icon, a legend swatch) cannot flip the verdict
            positions = [i for i in (block.find("\\end{tikzpicture}"),
                                     block.find("\\includegraphics")) if i >= 0]
            content = min(positions) if positions else -1
            teaser = re.search(r"\\label\{fig:(?:teaser|hero)\}", block) is not None
            if cap < 0:
                if teaser:
                    rep.note("teaser_uncaptioned", "page-1 teaser carries no caption, as contracted", where)
                else:
                    rep.error("figure_no_caption", "figure has no caption", where)
            elif teaser:
                rep.error("teaser_caption", "the page-1 teaser carries no numbered caption", where)
            else:
                if content >= 0 and cap < content:
                    rep.error("figure_caption_above", "figure caption must be below the graphic", where)
                if not CAPTION_LEAD.search(block[cap:cap + 60]):
                    rep.warn("figure_caption_lead", "caption should open with a bold lead phrase", where)
            if "\\label{" not in block:
                rep.error("figure_no_label", "figure has no \\label", where)
            manifest = re.search(r"%\s*source-data:", path.read_text(encoding="utf-8"))
            if not manifest:
                if "\\begin{axis}" in block:
                    rep.warn("figure_no_manifest",
                             "data plot has no '% source-data:' / '% generator:' manifest", where)
                elif "\\includegraphics" in block:
                    rep.note("figure_no_manifest",
                             "included artwork has no '% source-data:' / '% generator:' manifest", where)

    hero = paper / "figures/hero.tex"
    opening_kind = (design or {}).get("opening")
    if hero.exists() and opening_kind in (None, "design-card"):
        if "\\caption" in strip_comments(hero.read_text(encoding="utf-8")):
            rep.error("teaser_caption", "the page-1 teaser carries no numbered caption", "figures/hero.tex")
    opening = paper / "figures/opening.tex"
    if design and opening.exists():
        src = strip_comments(opening.read_text(encoding="utf-8"))
        if opening_kind in ("results", "results-wide"):
            if not re.search(r"\\caption(?:of\{figure\})?\s*\{", src):
                rep.error("opening_uncaptioned", f"opening `{opening_kind}` is a numbered, captioned "
                          "figure (P1/P2/P7); figures/opening.tex has no caption", "figures/opening.tex")
            if "\\label{fig:opening}" not in src:
                rep.error("opening_unlabeled", "figures/opening.tex must carry \\label{fig:opening}",
                          "figures/opening.tex")
        elif opening_kind == "composite" and re.search(r"\\caption(?:of)?\s*[\[{]", src):
            rep.error("composite_captioned", "the composite opening (P3) is unnumbered and uncaptioned",
                      "figures/opening.tex")
        elif opening_kind == "none" and re.search(r"\\begin\{(?:figure|tikzpicture)|\\includegraphics", src):
            rep.error("opening_not_none", "the design drew opening=none but figures/opening.tex draws something",
                      "figures/opening.tex")
    return stats


NUMBER = re.compile(r"-?\d+(?:[.,]\d+)*(?:\.\d+)?")


def normalize_number(raw: str) -> str:
    """Comparable form: no sign, no thousands separators, no trailing zeros."""
    text = raw.lstrip("+-").replace("{,}", "").replace(",", "")
    if "." in text:
        text = text.rstrip("0").rstrip(".") or "0"
    return text.lstrip("0") or "0"


def header_numbers(header: str) -> set[str]:
    r"""Numbers visible only in a column header, e.g. ``$k$=16`` or ``(ms)``.

    numeric_columns() drops everything above the first \midrule on purpose:
    a header's own precision must never be compared against the data's. But
    a header-only number (a sweep value named in the column label, a percent
    in a units tag) is still something a reader can look up in the table, so
    the traceability check (every abstract/conclusion number reported by some
    float) must see it too. A table forcing an author to transpose rows and
    columns just to make a number appear below the rule is a checker defect,
    not a layout improvement.
    """
    text = re.sub(r"\\Block\{[^{}]*\}", " ", header)
    for cmd in ("toprule", "midrule", "bottomrule", "cmidrule", "hline"):
        text = re.sub(rf"\\{cmd}(?:\[[^\]]*\])?(?:\([^)]*\))?(?:\{{[^}}]*\}})?", " ", text)
    text = re.sub(r"\\[A-Za-z@]+\*?", " ", text)
    text = re.sub(r"[{}$~]", " ", text)
    return {normalize_number(n) for n in NUMBER.findall(text)}


def evidence_numbers(paper: Path) -> set[str]:
    """Every number a reader can look up: table cells, teaser macros, plot data."""
    found: set[str] = set()
    for path in tex_files(paper):
        src = strip_comments(path.read_text(encoding="utf-8"))
        for block in re.findall(r"\\begin\{(?:table\*?|acwidetable)\}(?:\[[^\]]*\])?(.*?)\\end\{(?:table\*?|acwidetable)\}", src, flags=re.S):
            for body in tabular_bodies(block):
                for column in numeric_columns(body):
                    for cell in column:
                        if is_numeric_cell(cell):
                            found |= {normalize_number(n) for n in NUMBER.findall(cell)}
                cut = re.search(r"\\midrule(?:\[[^\]]*\])?", body)
                found |= header_numbers(body[:cut.start()] if cut else "")
    data = paper / "data"
    if data.is_dir():
        for path in list(data.glob("*.tex")) + list(data.glob("*.dat")):
            text = re.sub(r"^\s*[%#].*$", "", path.read_text(encoding="utf-8"), flags=re.M)
            found |= {normalize_number(n) for n in NUMBER.findall(text)}
    return found


def numbers_in_prose(text: str) -> list[str]:
    """Numbers a reader sees, including inside inline math.

    to_prose() drops math, but a paper states its results as $0.011 \\pm 0.005$,
    so scanning its output would check nothing. Strip only the commands whose
    arguments carry digits that are not claims: citation keys, labels, and
    cross-references.
    """
    text = strip_comments(text)
    # Acknowledgments carry grant and award numbers, which are neither claims
    # nor results. Everything from that heading on is institutional boilerplate.
    text = re.split(r"\\section\*\{\s*Acknowledg", text)[0]
    text = re.sub(r"\\(?:cite[a-z]*|C?ref|cref|eqref|label|input|includegraphics)"
                  r"\s*(?:\[[^\]]*\])?\{[^}]*\}", " ", text)
    text = text.replace("{,}", "").replace("\\,", "")
    return NUMBER.findall(text)


def check_reported_numbers(paper: Path, rep: Report, submission: bool) -> dict:
    untraceable = rep.error if submission else rep.warn
    """Abstract and conclusion may only state numbers a float already reports."""
    evidence = evidence_numbers(paper)
    stats = {"evidence_numbers": len(evidence), "unsupported": []}
    for stem, rule in (("00_abstract", "the abstract may not state a number absent from a table"),
                       ("05_conclusion", "the conclusion introduces no new number")):
        path = paper / "sections" / f"{stem}.tex"
        if not path.exists():
            continue
        for raw in numbers_in_prose(path.read_text(encoding="utf-8")):
            value = normalize_number(raw)
            if value in evidence:
                continue
            stats["unsupported"].append({"section": stem, "value": raw})
            untraceable("unsupported_number",
                      f"'{raw}' appears in prose but in no table cell, teaser macro, or "
                      f"plot data file; {rule}. A gain computed from two tabled values is "
                      "still untraceable: put it in the table or drop it.",
                      f"sections/{stem}.tex")
    return stats


def macro_body_spans(text: str) -> list[tuple[int, int]]:
    """Character spans of the bodies of \\newcommand / \\renewcommand /
    \\providecommand definitions, found by brace matching."""
    spans = []
    for m in re.finditer(r"\\(?:re|provide)?newcommand\*?\s*\{?\\[A-Za-z@]+\}?\s*(?:\[[^\]]*\]\s*)*\{", text):
        depth, i = 1, m.end()
        while i < len(text) and depth:
            c = text[i]
            if c == "\\":
                i += 2
                continue
            depth += (c == "{") - (c == "}")
            i += 1
        spans.append((m.end(), i))
    return spans


def unwrap_macro_blocks(text: str) -> str:
    r"""Keep the bodies of \newcommand / \renewcommand definitions as prose.

    `to_prose()` strips a definition together with its argument. That is right
    for `macros.tex`, where the body is a terminology string, and wrong for the
    blocks whose whole rendered content sits inside one hook definition --
    every `blocks/limitations/*.tex` does, so the Limitations section counted
    as **zero words** toward its host section and toward the main body, in
    every design, silently. The writer then had to clear the main-body floor
    without the credit the design brief's own arithmetic promises.
    """
    spans = macro_body_spans(text)
    if not spans:
        return text
    heads = {m.end(): m.start() for m in re.finditer(
        r"\\(?:re|provide)?newcommand\*?\s*\{?\\[A-Za-z@]+\}?\s*(?:\[[^\]]*\]\s*)*\{", text)}
    out, pos = [], 0
    for start, end in spans:
        head = heads.get(start)
        if head is None or head < pos:
            continue
        out.append(text[pos:head])
        out.append(" " + text[start:end - 1] + " ")
        pos = end
    out.append(text[pos:])
    return "".join(out)


def check_placeholders(paper: Path, rep: Report, submission: bool) -> None:
    for path in tex_files(paper):
        if path.name in {"preamble.tex", "macros.tex"}:
            continue
        text = path.read_text(encoding="utf-8")
        rel = str(path.relative_to(paper.parent))
        for pattern, label in FORBIDDEN.items():
            for m in re.finditer(pattern, text):
                line_start = text.rfind("\n", 0, m.start()) + 1
                line = text[line_start:text.find("\n", m.start())]
                if "\\newcommand" in line or "\\def" in line:
                    continue
                rep.error("forbidden_content", f"{label}: '{m.group(0)}'",
                          f"{rel}:{text.count(chr(10), 0, m.start()) + 1}")
        macro_spans = macro_body_spans(text)
        for m in re.finditer(r"\\slot\{([^}]*)\}", text):
            where = f"{rel}:{text.count(chr(10), 0, m.start()) + 1}"
            in_macro = any(a <= m.start() < b for a, b in macro_spans)
            if submission and not in_macro:
                rep.error("unfilled_slot", f"\\slot{{{m.group(1)}}} remains in a submission build", where)
            elif submission:
                # A slot inside a \newcommand body renders only if the macro is
                # invoked; build_paper.sh --final refuses it then, which is the
                # real gate. Here it is a pointer, not a verdict.
                rep.note("open_slot_in_macro",
                         f"\\slot{{{m.group(1)}}} sits in a macro body; fill it if the macro is used, "
                         "or delete the macro", where)
            else:
                rep.note("open_slot", f"\\slot{{{m.group(1)}}} awaiting evidence", where)


def find_build_aux(paper: Path) -> Path | None:
    """The aux file from the most recent build, or None if the paper was
    never compiled.

    build_paper.sh writes paper/build/main.aux for a draft build and
    paper/build/main_final.aux for --final. Either reflects what LaTeX
    actually resolved; prefer whichever was written most recently, since
    that is the build closest to the current source.
    """
    build_dir = paper / "build"
    if not build_dir.is_dir():
        return None
    candidates = [p for p in (build_dir / "main.aux", build_dir / "main_final.aux") if p.exists()]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def aux_resolved_labels(aux_path: Path) -> set[str]:
    r"""Label keys LaTeX actually wrote to the compiled aux file.

    cleveref writes its own copy of every label as ``key@cref``, independent
    of the plain \newlabel{key} that hyperref/caption write. A \cref usage
    resolves so long as either form is present, so both collapse to the same
    base key here; a key present in neither is the label that never made it
    into the build -- the one that source text alone cannot distinguish from
    a label that compiled cleanly.
    """
    text = aux_path.read_text(encoding="utf-8", errors="replace")
    keys = re.findall(r"\\newlabel\{([^}]*)\}", text)
    return {re.sub(r"@cref$", "", k) for k in keys}


UNDEFINED_REF_LOG = re.compile(r"Reference `([^']+)' on page \d+ undefined")


def log_undefined_refs(log_path: Path) -> set[str] | None:
    r"""Keys the *.log itself says were undefined during this build, or None
    when the log is unavailable.

    A label can be absent from aux_resolved_labels() for a completely benign
    reason: it sits inside a guarded Tier-D figure (figure-ladder.md) whose
    \IfFileExists branch never ran because the data file is absent, and the
    \cref narrating it is guarded the same way, so neither ever reaches the
    typesetter. That is correct-by-design omission, not a silent drop, and it
    must not be flagged. LaTeX only ever writes "Reference `key' ... undefined"
    when a \ref/\cref/\eqref/\autoref was actually processed and failed to
    resolve, so the log is the one signal that tells the two cases apart.
    """
    if not log_path.exists():
        return None
    text = log_path.read_text(encoding="utf-8", errors="replace")
    return set(UNDEFINED_REF_LOG.findall(text))


def check_references(paper: Path, rep: Report, submission: bool = False, design: dict | None = None) -> dict:
    labels: set[str] = set()
    refs: dict[str, str] = {}
    cites: dict[str, str] = {}
    for path in tex_files(paper):
        src = strip_comments(path.read_text(encoding="utf-8"))
        rel = str(path.relative_to(paper.parent))
        labels |= set(re.findall(r"\\label\{([^}]*)\}", src))
        for key in re.findall(r"\\(?:C?ref|cref|eqref|autoref)\{([^}]*)\}", src):
            for part in key.split(","):
                refs.setdefault(part.strip(), rel)
        for group in re.findall(r"\\cite[a-z]*\*?(?:\[[^\]]*\])*\{([^}]*)\}", src):
            for part in group.split(","):
                cites.setdefault(part.strip(), rel)

    for key, rel in refs.items():
        if key and key not in labels:
            rep.error("undefined_reference", f"\\ref to '{key}' has no \\label", rel)
    for label in sorted(labels):
        if label.startswith(("tab:", "fig:", "eq:")) and label not in refs:
            rep.warn("unreferenced_float", f"'{label}' is never referenced from prose")

    # A \label{...} sitting in the source text is not proof LaTeX registered
    # it. A label split away from its \caption by a wrapper (a threeparttable
    # around a resizebox'd NiceTabular is the construct that has actually done
    # this) can compile clean and print a literal '??' for every \ref to it,
    # while a source-only scan sees nothing wrong. Cross-check against the
    # aux file from the most recent build when one is available; degrade to a
    # warning, never silence, when the paper has never been built.
    aux_path = find_build_aux(paper)
    aux_resolved: set[str] | None = None
    if aux_path is not None:
        aux_resolved = aux_resolved_labels(aux_path)
        aux_rel = str(aux_path.relative_to(paper.parent))
        log_undefined = log_undefined_refs(aux_path.with_suffix(".log"))
        for key, rel in refs.items():
            if not (key and key in labels and key not in aux_resolved):
                continue
            # Confirm against the log when one is available: a guarded
            # Tier-D figure whose data file is absent drops its \label and
            # its narrating \cref together (figure-ladder.md), so neither
            # was ever typeset and LaTeX never warned about either. Without
            # the log to tell that apart from a genuine silent drop, warn
            # rather than claim a defect that may not exist.
            if log_undefined is not None and key not in log_undefined:
                continue
            severity = rep.error if log_undefined is not None else rep.warn
            severity("reference_unresolved_in_build",
                      f"\\ref to '{key}' has a \\label in source, but {aux_rel} from the "
                      "most recent build never registered it -- LaTeX prints a literal "
                      "'??' here. The label likely sits inside a wrapper (e.g. a "
                      "threeparttable around a resizebox'd NiceTabular) that silently "
                      "dropped it; rebuild after moving \\label next to \\caption.",
                      rel)
        if log_undefined is None:
            rep.note("no_build_log",
                     f"{aux_rel} exists but its .log does not, so an unresolved label above "
                     "could not be confirmed against LaTeX's own 'Reference ... undefined' "
                     "warning; it is reported as a warning rather than an error, and may be "
                     "a guarded Tier-D figure correctly omitted together with its narrating "
                     "sentence. Keep --keep-logs (tectonic) so the next run can tell.")
    else:
        rep.warn("no_build_aux",
                 "no paper/build/main.aux or main_final.aux found; cross-reference "
                 "resolution was checked against source text only, which cannot tell a "
                 "\\label that compiled clean from one LaTeX silently failed to register. "
                 "Run build_paper.sh and re-run this check against the compiled aux before "
                 "trusting this gate on cross-references.")

    bib = paper / "references.bib"
    bib_keys: set[str] = set()
    if bib.exists():
        bib_keys = set(re.findall(r"@\w+\s*\{\s*([^,\s]+)\s*,", bib.read_text(encoding="utf-8")))
        for key, rel in cites.items():
            if key and key not in bib_keys:
                rep.error("missing_bib_entry", f"\\cite{{{key}}} has no entry in references.bib", rel)
        for key in sorted(bib_keys - set(cites)):
            rep.note("unused_bib_entry", f"'{key}' is in references.bib but never cited")
    else:
        rep.error("missing_bib", "paper/references.bib not found")

    cite_floor = MIN_MAIN_BODY_CITATIONS
    if design and "_citations" in design.get("budgets", {}):
        cite_floor = int(design["budgets"]["_citations"])
    if len(cites) < cite_floor:
        (rep.error if submission else rep.warn)("thin_citations",
                 f"{len(cites)} distinct citation keys; this design expects at least {cite_floor}")
    return {"labels": len(labels), "refs": len(refs), "cites": len(cites), "bib": len(bib_keys),
            "aux_checked": aux_resolved is not None,
            "aux_path": str(aux_path.relative_to(paper.parent)) if aux_path else None}


def check_pdf(pdf: Path, rep: Report, max_main_pages: int | None, submission: bool = False) -> dict:
    """Page count and page roles, read from the compiled artifact.

    Layout is a property of the PDF, not of the source. Text extraction cannot
    validate appearance, but it can validate structure: where the references
    begin, whether they start on their own page, and whether the main body fits
    the venue budget.

    In --submission mode, every path that leaves the page budget unverified
    (no PDF, no poppler, an unreadable PDF, no detectable References page)
    is itself an error, not a warning: submission mode exists to refuse a
    paper it cannot confirm is submittable, and a budget that was silently
    never checked is indistinguishable, from the outside, from one that
    passed.
    """
    unverifiable = rep.error if submission else rep.warn
    stats: dict = {"pages": None, "references_page": None, "appendix_page": None}
    if not pdf.exists():
        unverifiable("no_pdf", f"{pdf} not found; build before checking page roles")
        return stats
    if not shutil.which("pdftotext"):
        unverifiable("no_pdftotext", "poppler's pdftotext is not installed; page roles unchecked")
        return stats

    try:
        total = int(re.search(r"^Pages:\s+(\d+)", subprocess.run(
            ["pdfinfo", str(pdf)], capture_output=True, text=True, check=True).stdout,
            flags=re.M).group(1))
    except Exception as exc:                                   # noqa: BLE001
        unverifiable("pdf_unreadable", f"could not read {pdf}: {exc}")
        return stats
    stats["pages"] = total

    floats_per_page: list[int] = []
    for page in range(1, total + 1):
        text = subprocess.run(["pdftotext", "-f", str(page), "-l", str(page), str(pdf), "-"],
                              capture_output=True, text=True).stdout
        floats_per_page.append(len(re.findall(r"(?m)^(?:Figure|Table|Fig\.|Tab\.)\s*\d", text)))
        lines = [l for l in text.strip().splitlines() if l.strip()]
        head = "\n".join(lines[:3])
        # Small-caps headings (the ICLR style sets \section in \sc) make
        # pdftotext's default word reconstruction insert a space at the font
        # change: "R EFERENCES". Compare with whitespace removed, case-folded.
        flat = lambda t: re.sub(r"\s+", "", t).lower()
        if stats["references_page"] is None:
            if flat(head).startswith("references"):
                stats["references_page"] = page
                stats["references_at_top"] = True
            elif any(flat(l) == "references" for l in lines):
                # References follow the text on the same page (P2, P5, P6):
                # that page is still a main-body page for the budget.
                stats["references_page"] = page
                stats["references_at_top"] = False
                continue
        if stats["appendix_page"] is None and re.match(r"\s*A\b", head) and \
                stats["references_page"] is not None:
            stats["appendix_page"] = page

    if stats["references_page"] is None:
        unverifiable("no_references_page",
                      "no page begins with a References heading; the main-body page "
                      "count cannot be determined")
    else:
        main_pages = stats["references_page"] - (1 if stats.get("references_at_top", True) else 0)
        stats["main_pages"] = main_pages
        # How the evidence is spread, not just how much of it there is. A run of
        # main-body pages carrying no float at all reads as a wall of prose, and
        # no other gate can see it: the counts can be respectable while every
        # float sits in the last two pages. The sparsest of the seven source
        # papers (P5: two figures, ten tables) still breaks its text at least
        # every other page.
        body = floats_per_page[:main_pages]
        stats["floats_per_page"] = body
        run = best = 0
        start = best_start = 1
        for i, n in enumerate(body, start=1):
            if n == 0:
                if run == 0:
                    start = i
                run += 1
                if run > best:
                    best, best_start = run, start
            else:
                run = 0
        stats["longest_floatless_run"] = best
        if best >= 4:
            rep.warn("floatless_stretch",
                     f"pages {best_start}-{best_start + best - 1} of the main body carry no figure "
                     f"and no table ({best} consecutive pages of prose). The float counts may be "
                     "fine while their placement is not: move a table or the secondary figure "
                     "into that stretch, or give the section it spans something to look at.")
        if max_main_pages is not None and main_pages > max_main_pages:
            rep.error("page_budget",
                      f"main body runs to page {main_pages}; the venue budget is "
                      f"{max_main_pages}. Move detail to the appendix rather than "
                      "shrinking type or editing the style file.")
        if stats["appendix_page"] is not None and stats["appendix_page"] <= stats["references_page"]:
            rep.error("appendix_before_references",
                      "the lettered appendix must follow the references")
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--paper-dir", default="paper", help="directory holding main.tex")
    parser.add_argument("--submission", action="store_true",
                        help="treat remaining \\slot markers as errors")
    parser.add_argument("--pdf", type=Path,
                        help="compiled PDF; enables page-count and page-role checks")
    parser.add_argument("--max-main-pages", type=int,
                        help="venue budget for the main body, references excluded")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    paper = Path(args.paper_dir).resolve()
    if not paper.is_dir():
        print(f"paper directory not found: {paper}", file=sys.stderr)
        return 2

    rep = Report()
    design = load_design(paper)
    layout = check_layout(paper, rep, design)
    budgets = check_budgets(paper, rep, args.submission, design)
    check_abstract(paper, rep)
    equations = check_equations(paper, rep, args.submission, design)
    tables = check_tables(paper, rep, design)
    table_extremes = check_table_extremes(paper, rep, design)
    figures = check_figures(paper, rep, design)
    icons = check_icons(paper, rep)
    numbers = check_reported_numbers(paper, rep, args.submission)
    check_placeholders(paper, rep, args.submission)
    xrefs = check_references(paper, rep, args.submission, design)
    if args.pdf:
        pdf = check_pdf(args.pdf, rep, args.max_main_pages, args.submission)
        if args.max_main_pages is None:
            rep.warn("no_page_budget_declared",
                     "--pdf was given without --max-main-pages; the page-count ceiling "
                     "is not being enforced")
    elif args.submission:
        rep.error("missing_pdf_submission",
                  "--submission was given without --pdf; a missing PDF cannot be "
                  "confirmed submittable, and the whole point of submission mode is "
                  "to refuse exactly that silently")
        pdf = {}
    else:
        pdf = {}

    verdict = "PASS" if rep.blocking == 0 else "BLOCKED"
    result = {
        "verdict": verdict,
        "paper_dir": str(paper),
        "design": {k: v for k, v in (design or {}).items() if k not in ("budgets", "evidence")} or None,
        "submission_mode": args.submission,
        "sections": layout.get("sections", []),
        "word_counts": budgets,
        "equations": equations,
        "floats": {**tables, **figures},
        "table_extremes": table_extremes,
        "reported_numbers": numbers,
        "cross_references": xrefs,
        "pdf": pdf,
        "error_count": rep.blocking,
        "issue_count": len(rep.items),
        "issues": rep.items,
    }

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"{verdict}: {rep.blocking} error(s), {len(rep.items)} issue(s)")
        if design:
            print(f"  design       seed {design.get('seed')} · {design.get('layout')} · opening={design.get('opening')} "
                  f"· experiments={design.get('experiments')} · table={design.get('main_table')} "
                  f"· ablation={design.get('ablation')} · eqs={design.get('equations')}")
        else:
            print("  design       (none: legacy single-exemplar rules)")
        body_env = tuple(design["budgets"]["_main_body"]) if design and "_main_body" in design.get("budgets", {}) else MAIN_BODY_BUDGET
        eq_floor = int(design.get("equation_floor", MIN_METHOD_EQUATIONS)) if design else MIN_METHOD_EQUATIONS
        print(f"  sections     {' -> '.join(result['sections']) or '(none)'}")
        print(f"  main body    {budgets.get('_main_body', 0)} words "
              f"(envelope {body_env[0]}-{body_env[1]})")
        print(f"  method eqs   {equations['method_equations']} (min {eq_floor})")
        print(f"  floats       {tables['tables']} table(s), {figures['figures']} figure(s)")
        print(f"  citations    {xrefs['cites']} key(s) against {xrefs['bib']} bib entr(ies)")
        aux_state = xrefs.get('aux_path') if xrefs.get('aux_checked') else 'not built; source only'
        print(f"  aux          {aux_state}")
        print(f"  table bold   {table_extremes['columns_checked']} column(s) checked, "
              f"{table_extremes['flagged']} flagged")
        print(f"  numbers      {numbers['evidence_numbers']} reported by floats; "
              f"{len(numbers['unsupported'])} stated in prose without one")
        if pdf.get("pages"):
            print(f"  pdf          {pdf['pages']} pages; main body {pdf.get('main_pages', '?')}, "
                  f"references from {pdf.get('references_page', '?')}, "
                  f"appendix from {pdf.get('appendix_page', '?')}")
        order = {"error": 0, "warning": 1, "advisory": 2}
        for item in sorted(rep.items, key=lambda i: order[i["severity"]]):
            loc = f" [{item['where']}]" if item["where"] else ""
            print(f"  {item['severity'].upper():9s} {item['code']}: {item['message']}{loc}")

    return 1 if rep.blocking else 0


if __name__ == "__main__":
    raise SystemExit(main())
