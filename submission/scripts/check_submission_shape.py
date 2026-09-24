#!/usr/bin/env python3
"""check_submission_shape -- is this a paper, as the platform will receive it?

Runs after `paper-writing` has produced a manuscript and `make_submission.py` has
rendered it into the platform's shape. Fourteen predicates over `submission.json`
and the figure directory; the evidence-side predicates moved to
`research/scripts/check_design_validity.py` per `interfaces/evidence-interface.md` §4.

It exists because a submission can pass every other check and still not be a paper.
The first one this pipeline produced had no equations, no figure, four citations
inherited from its seed paper's own response literature, and a title calling itself
"A Smoke-Scale Pipeline Demonstration" while the abstract twice declared its own
results unusable. It scores 4/21.

Several predicates encode facts read from the platform's own renderer
(`src/lib/markdown.ts`), not guesses:

  no_stray_dollar              math is extracted before markdown runs, so an
                               unpaired `$` swallows a span or throws
  no_anchor_links              no heading ids are emitted; `[x](#results)` is dead
  results_table                GFM tables render, and reviewers are agents reading
                               `body_md` as source -- a number only in a figure is
                               invisible to them
  figure_embedded_in_markdown  an uploaded attachment the markdown never embeds
                               does not exist for those reviewers. This pipeline
                               uploaded figures for fifteen steps and referenced
                               none of them.
  method_code_map              every mechanism the Method claims must name a
                               grep-able anchor in the experiment code

    check_submission_shape.py <workspace> [--quality FILE] [--warn-only]

Exit 0 = PASS or WARN, 1 = FAIL, 2 = BLOCKED (no submission.json).
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import verdict as aris_audit  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FIG_EXT = (".png", ".svg", ".jpg", ".jpeg", ".pdf")

# $$...$$ display math, and $...$ inline that is not part of a $$ pair.
DISPLAY_MATH = re.compile(r"\$\$(.+?)\$\$", re.S)
CITE_ARXIV = re.compile(r"arxiv[:\s]*\d{4}\.\d{4,5}", re.I)
CITE_BRACKET = re.compile(r"\[(\d{1,3})\]")
CITE_DOI = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.I)
CITE_AUTHORYEAR = re.compile(r"\(([A-Z][A-Za-z\-]+(?: et al\.?)?),? (?:19|20)\d{2}[a-z]?\)")

# Author-year citations as paper-writing renders them, counted one work at a
# time. The pattern above takes a parenthesis holding exactly one citation, so
# "(Bubeck et al., 2012; Agrawal et al., 2021)" counted as nothing, and nor did
# a surname with an accent (Tamás): a paper citing 35 works in groups read as
# citing one. Each ;-separated item counts, and "Author (2020)" in running text.
_NAME = r"[^\W\d_][\w'\u2019\-]*"
_AY_ITEM = re.compile(r"(" + _NAME + r"(?: et al\.?| (?:and|&) " + _NAME + r")?),? ((?:19|20)\d{2}[a-z]?)")
_AY_PAREN = re.compile(r"\(([^()]*\b(?:19|20)\d{2}[a-z]?[^()]*)\)")
_AY_TEXT = re.compile(r"(" + _NAME + r"(?: et al\.?)?) \(((?:19|20)\d{2}[a-z]?)\)")


def author_year_cites(text: str) -> set:
    out = set()
    for m in _AY_PAREN.finditer(text):
        for item in m.group(1).split(";"):
            im = _AY_ITEM.search(item.strip())
            if im:
                out.add(f"{im.group(1)}, {im.group(2)}")
    for m in _AY_TEXT.finditer(text):
        out.add(f"{m.group(1)}, {m.group(2)}")
    return out
# a reported interval, either bracketed or +/-
CI_NOTATION = re.compile(r"\[\s*-?\d*\.?\d+\s*,\s*-?\d*\.?\d+\s*\]|±\s*\d*\.?\d+|\+/-\s*\d*\.?\d+")



# ── scope ────────────────────────────────────────────────────────────────────
# These predicates used to live in one gate over both the manuscript and the
# evidence. `interfaces/evidence-interface.md` §4 assigns the evidence ones to the
# research side -- "rules the research side owns because the writing side cannot
# check them" -- so the same implementation is filtered to a scope rather than
# duplicated and allowed to drift.
DESIGN_CHECKS = {'min_n_per_cell', 'truncation_rate', 'model_count', 'no_denominator_only_condition', 'cells_found', 'complexity_levels', 'real_complexity_ladder'}
SCOPE = "manuscript"


def in_scope(name: str) -> bool:
    return (name in DESIGN_CHECKS) if SCOPE == "design" else (name not in DESIGN_CHECKS)


def wilson(k: int, n: int, z: float = 1.96) -> tuple:
    """Wilson score interval -- the one quality.json mandates, reproduced here
    so the gate can say what a cell's interval actually is when it complains."""
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, centre - half), min(1.0, centre + half))


def inline_math_count(text: str) -> int:
    """Count $...$ spans after removing $$...$$ blocks, so display math is not
    double-counted and a stray currency figure does not inflate the total."""
    stripped = DISPLAY_MATH.sub(" ", text)
    return len(re.findall(r"(?<!\$)\$(?!\$)([^\$\n]{1,200}?)(?<!\$)\$(?!\$)", stripped))


def load_cells(workdir: str) -> list:
    """Every (model, condition, level) cell we can find in the results, with its
    n, its successes and its truncation count. Tolerant about layout: the
    experiment code is written fresh each run, so the field names vary."""
    cells = {}
    seen = set()          # (model, condition, level, instance) -- one vote each
    unattributed = 0      # records with no model we can name
    rdir = os.path.join(workdir, "runs")
    for dirpath, _, names in os.walk(rdir):
        for name in sorted(names):
            if name in ("manifest.json", "MANIFEST.json", "REPLAY_MANIFEST.json",
                        "REPRO_GATE.json") or not name.endswith((".json", ".jsonl")):
                continue
            try:
                recs = _load_any(os.path.join(dirpath, name))
            except (OSError, ValueError):
                continue
            # A results file may name its model once, at the top, rather than
            # on every record. (This read `doc`, a name never defined here, and
            # crashed the gate on any record without its own model field --
            # that is, on every study that is not about language models.)
            file_model = None
            if name.endswith(".json"):
                try:
                    top = json.load(open(os.path.join(dirpath, name), encoding="utf-8"))
                    if isinstance(top, dict):
                        file_model = top.get("model")
                except (OSError, ValueError):
                    pass
            for rec in recs:
                if not isinstance(rec, dict):
                    continue
                lvl = rec.get("level", rec.get("n_nodes", rec.get("complexity")))
                if lvl is None:
                    continue
                # A record with no attributable model cannot be counted: the same
                # instance is usually written twice (once by the generator, once
                # by the scorer), and treating the scorer's copy as a second
                # nameless "model" both doubles n and fakes a second model. That
                # is exactly the way an under-powered run would sneak past.
                model = rec.get("model") or file_model
                if not model:
                    unattributed += 1
                    continue
                key = (str(model), str(rec.get("condition", "raw")), str(lvl))
                inst = str(rec.get("id") or rec.get("instance_id") or
                           rec.get("instance") or f"__pos{len(seen)}")
                if (key, inst) in seen:
                    continue
                seen.add((key, inst))
                c = cells.setdefault(key, {"n": 0, "correct": 0, "truncated": 0})
                c["n"] += 1
                if rec.get("correct") or rec.get("raw_correct") or rec.get("is_correct"):
                    c["correct"] += 1
                if rec.get("truncated"):
                    c["truncated"] += 1
    out = [{"model": k[0], "condition": k[1], "level": k[2], **v}
           for k, v in sorted(cells.items())]
    if unattributed:
        out.append({"model": "__unattributed__", "condition": "-", "level": "-",
                    "n": unattributed, "correct": 0, "truncated": 0,
                    "note": "records with no model field, excluded from every check"})
    return out


def aggregate_cells(workdir: str) -> list:
    """Conditions usually live in an aggregate block, not on the per-instance
    records -- scored.json carries {"scoring": {"<condition>": {"<level>":
    {"n","correct"}}}}. A detector that only reads per-instance records sees one
    condition and cannot notice that two of them differ only by exclusion, which
    is exactly the defect it exists to find.
    """
    out = []
    for dirpath, dirnames, names in os.walk(os.path.join(workdir, "runs")):
        dirnames[:] = [d for d in dirnames if d not in ("__pycache__",)]
        for n in names:
            if not n.endswith(".json"):
                continue
            try:
                doc = json.load(open(os.path.join(dirpath, n), encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not isinstance(doc, dict):
                continue
            model = doc.get("model", "?")
            for blockname in ("scoring", "aggregate", "summary", "by_condition"):
                block = doc.get(blockname)
                if not isinstance(block, dict):
                    continue
                for cond, per_level in block.items():
                    if not isinstance(per_level, dict):
                        continue
                    for lv, cell in per_level.items():
                        if not isinstance(cell, dict) or "n" not in cell:
                            continue
                        if str(lv).lower() in ("overall", "total", "all"):
                            continue
                        out.append({"model": str(model), "condition": str(cond),
                                    "level": str(lv), "n": cell.get("n") or 0,
                                    "correct": cell.get("correct") or 0,
                                    "truncated": cell.get("truncated") or 0,
                                    "_from": "aggregate"})
    return out


def _load_any(path: str) -> list:
    """Per-instance records, from either JSON or JSONL. The sweep writes 168
    records as JSONL, which is the sensible format for that; a gate that only
    reads .json silently sees an empty experiment."""
    if path.endswith(".jsonl"):
        out = []
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except ValueError:
                    continue
        return out
    with open(path, encoding="utf-8") as f:
        return _records(json.load(f))


def _records(doc):
    """Find the list of per-instance records wherever the run put it."""
    if isinstance(doc, list):
        return doc
    if isinstance(doc, dict):
        for key in ("records", "per_instance", "results", "instances", "generations"):
            v = doc.get(key)
            if isinstance(v, list):
                return v
    return []


# The study kind, which the pipeline writes after step 3. Only one check reads
# it: a theory paper's numerical checks are usually exact, and an interval
# around an exact computation is not a thing to demand. Without the file the
# gate behaves as it always did.
def study_kind(workdir: str) -> str:
    try:
        return open(os.path.join(workdir, "STUDY_KIND"), encoding="utf-8").read().strip()
    except OSError:
        return ""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("workdir")
    ap.add_argument("--quality", default=os.path.join(ROOT, "interfaces", "quality.example.json"))
    ap.add_argument("--warn-only", action="store_true",
                    help="report but do not fail; for inspecting a draft mid-write")
    a = ap.parse_args()

    q = json.load(open(a.quality, encoding="utf-8"))
    shape = q["paper_shape"]
    stats = q["statistics"]
    tok = q["token_budget"]

    sub_path = os.path.join(a.workdir, "submission.json")
    if not os.path.exists(sub_path):
        aris_audit.emit(a.workdir, "paper-shape", "BLOCKED", "no_submission",
                        f"No submission.json in {a.workdir}; nothing to shape-check.",
                        verifier="submission-shape")
        print("submission-shape: BLOCKED -- no submission.json", file=sys.stderr)
        sys.exit(2)
    sub = json.load(open(sub_path, encoding="utf-8"))
    title, abstract = sub.get("title", ""), sub.get("abstract", "")
    body = sub.get("body_md", "")
    hay = (abstract + "\n" + body)

    checks = []

    def chk(name, ok, detail, fatal=True):
        if not in_scope(name):
            return
        checks.append({"check": name, "pass": bool(ok), "detail": detail,
                       "severity": "fatal" if fatal else "warn"})

    # ---- mathematics ----------------------------------------------------
    disp = len(DISPLAY_MATH.findall(body))
    inl = inline_math_count(body)
    chk("display_equations", disp >= shape["min_display_equations"],
        f"{disp} display equations ($$...$$), need >= {shape['min_display_equations']}. "
        f"The platform renders LaTeX server-side, so there is no excuse for prose-only method.")
    chk("inline_math", inl >= shape["min_inline_math"],
        f"{inl} inline math spans, need >= {shape['min_inline_math']}")

    # ---- figures --------------------------------------------------------
    figdir = os.path.join(a.workdir, "figures")
    figs = sorted(f for f in (os.listdir(figdir) if os.path.isdir(figdir) else [])
                  if f.lower().endswith(FIG_EXT))
    chk("figures_exist", len(figs) >= shape["min_figures"],
        f"{len(figs)} figure file(s) in figures/ ({', '.join(figs) or 'none'}), "
        f"need >= {shape['min_figures']}")
    if shape.get("require_figure_referenced_in_text") and figs:
        named = [f for f in figs
                 if os.path.splitext(f)[0] in body or f in body]
        generic = re.findall(r"(?:Figure|Fig\.?)\s*\d+", body, re.I)
        chk("figure_referenced", bool(named or generic),
            f"{len(named)} figure(s) referenced by filename, {len(generic)} by 'Figure N'. "
            f"A figure nobody points at is decoration.")
        # Stronger, and the one that actually mattered: an attachment the markdown
        # never embeds is invisible to a reviewer, because reviewers are agents
        # reading body_md as source and cannot open an attachment list.
        embedded = re.findall(r"!\[[^\]]*\]\(([^)]+)\)", body)
        chk("figure_embedded_in_markdown", bool(embedded),
            f"{len(embedded)} markdown image(s) in body_md. An uploaded figure that "
            f"body_md never embeds does not exist for the reviewers, who read "
            f"body_md as source. Use ![caption](/api/v1/attachments/<id>), and take "
            f"the id from the attach response rather than building the path.")

    # ---- citations ------------------------------------------------------
    cites = set(m.group(0).lower() for m in CITE_ARXIV.finditer(hay))
    cites |= set(m.group(0).lower() for m in CITE_DOI.finditer(hay))
    cites |= author_year_cites(hay)
    brackets = set(CITE_BRACKET.findall(hay))
    total_cites = len(cites) + len(brackets)
    chk("citations", total_cites >= shape["min_citations"],
        f"{total_cites} distinct citations ({len(cites)} identifier-style, "
        f"{len(brackets)} bracketed), need >= {shape['min_citations']}")

    # ---- reported uncertainty ------------------------------------------
    if shape.get("require_ci_in_results") and study_kind(a.workdir) != "theory":
        n_ci = len(CI_NOTATION.findall(body))
        chk("confidence_intervals", n_ci >= 2,
            f"{n_ci} interval notations in the body. quality.json requires the "
            f"{stats['ci_method']} interval to be reported, not just point estimates.")

    # ---- length and sections -------------------------------------------
    chk("body_length", len(body) >= shape["min_body_chars"],
        f"body_md is {len(body)} chars, need >= {shape['min_body_chars']}")
    heads = [h.lower() for h in re.findall(r"^#{1,4}\s*(?:\d+\.?\s*)?(.+)$", body, re.M)]

    # Limitations is checked separately, and softly, because requiring a section
    # NAMED "limitations" contradicted the writing side and nobody noticed.
    # `paper-writing`'s design family (references/design-axes.md, axis 12) draws
    # one of four placements, each traced to a real paper:
    #
    #   own-section          P6 -- an unnumbered Limitations section
    #   appendix             P3 P5 -- a lettered appendix section
    #   conclusion-paragraph P2 P7 -- a bold-lead `Limitations.` paragraph
    #   absent               P1 -- not stated at all
    #
    # A heading-only test passes the first two and fails the last two, so four of
    # six papers in one batch failed this check for having the shape a published
    # paper has. The reviewer's ruling: "不是每一篇文章都必须要把 limitation 放在
    # 正文里，这 depends on 具体的篇幅" -- it depends on how much room the paper has.
    #
    # So: recognise all four, and make absence a WARNING rather than a failure.
    # A missing limitations section is a quality remark for a human, not evidence
    # that the thing is not a paper, which is the only question this file asks.
    lim_head = any("limitation" in h for h in heads)
    lim_para = bool(re.search(r"^\s*(?:\*\*|__)\s*limitations?\b", body, re.M | re.I))
    # An entry is a ROLE: either one name or a list of names that all mean the
    # same role, any of which satisfies it. See `_required_sections_why` in
    # quality.json -- a literal single string failed real papers for calling
    # their setup "Experimental Setting" and their results "Main Evaluation".
    missing = []
    for role in shape["required_sections"]:
        names = [role] if isinstance(role, str) else list(role)
        if names and names[0] == "limitations":
            continue        # its own non-fatal check below
        if not any(n in h for n in names for h in heads):
            missing.append(names[0])
    chk("sections", not missing,
        f"missing sections: {missing or 'none'} (found: {heads})")
    chk("limitations_stated",
        lim_head or lim_para,
        ("limitations as a heading" if lim_head else
         "limitations as a bold-lead paragraph" if lim_para else
         "no limitations anywhere -- allowed (design axis 12 draws `absent`, as P1 does) "
         "but worth a human's eye, because a paper with room for them and none stated "
         "reads as one that did not look"),
        fatal=False)

    # ---- the self-defeating checks -------------------------------------
    bad_title = [w for w in shape["forbidden_in_title"] if w.lower() in title.lower()]
    chk("title_not_self_deprecating", not bad_title,
        f"title contains {bad_title or 'nothing disqualifying'}. "
        f"A title that calls the work a pilot tells a reviewer to stop reading.")
    bad_abs = [p for p in shape["forbidden_phrases_in_abstract"]
               if p.lower() in abstract.lower()]
    chk("abstract_makes_a_claim", not bad_abs,
        f"abstract contains {bad_abs or 'no blanket disclaimer'}. "
        f"Limits belong in the limitations section, stated specifically.")

    # ---- statistical power, from the results themselves -----------------
    all_cells = load_cells(a.workdir)
    cells = [c for c in all_cells if c["model"] != "__unattributed__"]
    unattr = next((c["n"] for c in all_cells if c["model"] == "__unattributed__"), 0)
    if unattr:
        print(f"shape-gate: {unattr} result record(s) carry no model field and were "
              f"excluded from the power checks", file=sys.stderr)
    if not cells:
        chk("cells_found", False,
            "could not find per-instance records under runs/ -- cannot check power", fatal=True)
    else:
        thin = [c for c in cells if c["n"] < stats["min_n_per_cell"]]
        chk("min_n_per_cell", not thin,
            f"{len(thin)}/{len(cells)} cells below n={stats['min_n_per_cell']}"
            + (f"; e.g. {thin[0]['model']}/{thin[0]['condition']}/L{thin[0]['level']} "
               f"has n={thin[0]['n']}, Wilson 95% = "
               f"[{wilson(thin[0]['correct'], thin[0]['n'])[0]:.2f}, "
               f"{wilson(thin[0]['correct'], thin[0]['n'])[1]:.2f}]" if thin else ""))
        cap = tok["max_truncation_rate_per_cell"]
        over = [c for c in cells if c["n"] and c["truncated"] / c["n"] > cap]
        chk("truncation_rate", not over,
            f"{len(over)}/{len(cells)} cells exceed a {cap:.0%} truncation rate"
            + (f"; worst is {over[0]['model']}/L{over[0]['level']} at "
               f"{over[0]['truncated']}/{over[0]['n']}. Above this the number "
               f"measures the token cap, not the model." if over else ""))
        models = {c["model"] for c in cells}
        chk("model_count", len(models) >= q["models"]["min_count"],
            f"{len(models)} model(s) in the results ({sorted(models)}), "
            f"need >= {q['models']['min_count']}")
        levels = {c["level"] for c in cells}
        chk("complexity_levels", len(levels) >= q["design"]["min_complexity_levels"],
            f"{len(levels)} complexity levels ({sorted(levels)}), "
            f"need >= {q['design']['min_complexity_levels']}")

    # ---- platform hazards, from what the renderer actually does ---------
    if shape.get("forbid_unescaped_dollar"):
        # Code is skipped: a '$' there is meant literally. The platform does NOT
        # skip it -- its math pass runs before markdown (src/lib/markdown.ts; a
        # bug reported 2026-09-23) -- so a '$' pair inside code is not seen here.
        probe = re.sub(r"```.*?```", " ", body, flags=re.S)
        probe = re.sub(r"`[^`\n]*`", " ", probe)
        probe = DISPLAY_MATH.sub(" ", probe)
        probe = re.sub(r"(?<!\$)\$(?!\$)([^\$\n]{1,200}?)(?<!\$)\$(?!\$)", " ", probe)
        stray = [m.start() for m in re.finditer(r"(?<!\\)\$", probe)]
        chk("no_stray_dollar", not stray,
            f"{len(stray)} unpaired, unescaped '$' outside math and code. "
            f"On the platform an unescaped '$' is math syntax: any later '$' on "
            f"the same line turns the span between them into math. Escape as \\$."
            + (f" First at char {stray[0]}: ...{probe[max(0,stray[0]-40):stray[0]+40]!r}"
               if stray else ""))

    if shape.get("forbid_anchor_links"):
        anchors = re.findall(r"\]\(#[^)]+\)", body)
        chk("no_anchor_links", not anchors,
            f"{len(anchors)} in-page anchor link(s) {anchors[:3]}. The renderer emits no "
            f"heading ids, so these are dead links. Cross-reference by section name.")

    if shape.get("min_results_tables"):
        # a GFM pipe table needs a delimiter row
        tables = len(re.findall(r"^\s*\|[\s:|-]*-[\s:|-]*\|\s*$", body, re.M))
        chk("results_table", tables >= shape["min_results_tables"],
            f"{tables} GFM pipe table(s), need >= {shape['min_results_tables']}. "
            f"Reviewers are agents reading body_md as JSON source: a number that "
            f"lives only in a figure is invisible to them.")

    if shape.get("require_png_figure"):
        pngs = [f for f in figs if f.lower().endswith((".png", ".jpg", ".jpeg"))]
        chk("png_figure", bool(pngs),
            f"raster figures: {pngs or 'none'}. SVG inline rendering is unverified on "
            f"this platform; ship PNG, and let SVG accompany it rather than replace it.")

    # ---- the three defect classes the adversarial review found -----------
    # D1: a Method section that describes software which does not exist.
    mcm = os.path.join(a.workdir, "METHOD_CODE_MAP.json")
    if os.path.exists(mcm):
        try:
            entries = json.load(open(mcm, encoding="utf-8"))
            entries = entries.get("mechanisms", entries) if isinstance(entries, dict) else entries
        except (OSError, ValueError):
            entries = None
        if entries is None:
            chk("method_code_map", False, f"{mcm} is not valid JSON")
        else:
            missing = []
            for e in entries:
                anchor_s = (e or {}).get("anchor") or ""
                claim = (e or {}).get("mechanism", "?")[:60]
                hit = False
                for dirpath, dirnames, names in os.walk(a.workdir):
                    dirnames[:] = [d for d in dirnames
                                   if d not in (".claude", ".aris", "archive-v1", "__pycache__")]
                    for n in names:
                        if not n.endswith(".py"):
                            continue
                        try:
                            if anchor_s and anchor_s in open(os.path.join(dirpath, n),
                                                             encoding="utf-8").read():
                                hit = True; break
                        except OSError:
                            pass
                    if hit: break
                if not hit:
                    missing.append(f"{claim!r} -> anchor {anchor_s!r} not found in any .py")
            chk("method_code_map", not missing,
                f"{len(missing)}/{len(entries)} method mechanisms have no code anchor"
                + (f"; e.g. {missing[0]}" if missing else "")
                + ". A Method section describing unwritten software is the defect that "
                  "desk-rejected the previous submission.")
    else:
        chk("method_code_map", False,
            f"no METHOD_CODE_MAP.json. Every mechanism the Method section claims must "
            f"name a grep-able anchor in the experiment code. The previous paper "
            f"described a continuation re-prompt that was implemented nowhere.",
            fatal=False)

    # D2: a 'correction' condition that only edits a denominator is an algebraic
    # identity, not a measurement -- it cannot come out flat, so it cannot falsify.
    agg = aggregate_cells(a.workdir)
    cond_cells = agg if agg else cells
    if cond_cells:
        by = {}
        for c in cond_cells:
            by.setdefault((c["model"], c["level"]), {})[c["condition"]] = c
        noop = []
        for (m, lv), conds in by.items():
            names = sorted(conds)
            for i in range(len(names)):
                for j in range(len(names)):
                    if i == j:
                        continue
                    x, y = conds[names[i]], conds[names[j]]
                    if (x["correct"] == y["correct"] and x["n"] > y["n"] and y["n"] > 0):
                        noop.append(f"{m}/L{lv}: '{names[j]}' has the same numerator as "
                                    f"'{names[i]}' ({x['correct']}) with a smaller "
                                    f"denominator ({y['n']} vs {x['n']})")
        chk("no_denominator_only_condition", not noop,
            f"{len(noop)} condition pair(s) differ only by exclusion"
            + (f"; {noop[0]}" if noop else "")
            + ". Dropping rows that are all wrong can only raise the rate, so the "
              "'correction' is an identity of the exclusion rule and no outcome could "
              "falsify it. Make it a second generation condition with the denominator "
              "held fixed.", fatal=bool(noop))

    # D3: is there actually a complexity ladder, or is the level label the only
    # thing that changes? A certified difficulty metric that is a constant offset
    # of the level is not a ladder.
    diff = {}
    for dirpath, dirnames, names in os.walk(os.path.join(a.workdir, "runs")):
        dirnames[:] = [d for d in dirnames if d not in ("__pycache__",)]
        for n in names:
            if not n.endswith(".json"):
                continue
            try:
                doc = json.load(open(os.path.join(dirpath, n), encoding="utf-8"))
            except (OSError, ValueError):
                continue
            for rec in _records(doc):
                if not isinstance(rec, dict):
                    continue
                lv = rec.get("level")
                for key in ("true_search_tree_size", "search_tree_size", "difficulty",
                            "certified_difficulty", "n_nodes"):
                    if lv is not None and isinstance(rec.get(key), (int, float)):
                        diff.setdefault(key, {}).setdefault(str(lv), []).append(rec[key])
    if diff:
        key = next(iter(diff))
        levels = sorted(diff[key], key=lambda x: (len(x), x))

        def median(v):
            v = sorted(v); n = len(v)
            return v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2

        meds = [median(diff[key][lv]) for lv in levels]
        # Medians, not means: one hard instance in the top level pulls a mean up
        # far enough to fake a ladder. On the previous run the means were
        # 7.0/10.0/21.6 (ratio 3.09x, apparently fine) while the medians were
        # 7/9/11 -- a constant offset, i.e. no ladder at all.
        ratio = (max(meds) / min(meds)) if min(meds) else 0
        # A metric that is level + constant is a relabelling, not a difficulty axis.
        diffs = [meds[i + 1] - meds[i] for i in range(len(meds) - 1)]
        affine = len(diffs) > 1 and max(diffs) - min(diffs) <= 1
        ok = ratio >= 2.0 and not affine
        chk("real_complexity_ladder", ok,
            f"certified difficulty '{key}' MEDIANS across levels {levels} are {meds} "
            f"(ratio {ratio:.2f}x, need >= 2x"
            + (f"; and the level-to-level steps {diffs} are constant, so the metric is "
               f"level+offset -- a relabelling, not a difficulty axis" if affine else "")
            + f"). Means would have been {[round(sum(diff[key][lv])/len(diff[key][lv]),1) for lv in levels]}, "
              f"which is why this uses medians.", fatal=False)

    # ---- verdict --------------------------------------------------------
    failed = [c for c in checks if not c["pass"] and c["severity"] == "fatal"]
    warned = [c for c in checks if not c["pass"] and c["severity"] == "warn"]
    verdict = "PASS" if not failed else "FAIL"
    if verdict == "PASS" and warned:
        verdict = "WARN"

    summary = (f"{len(checks) - len(failed) - len(warned)}/{len(checks)} shape checks passed"
               + (f"; FAILED: {', '.join(c['check'] for c in failed)}" if failed else ""))
    aris_audit.emit(
        a.workdir, "paper-shape", verdict,
        "shaped_like_a_paper" if verdict != "FAIL" else "not_shaped_like_a_paper",
        summary,
        inputs=[sub_path, a.quality],
        reasoning=("Deterministic: every threshold is read from quality.json and every "
                   "check is a predicate over submission.json and the results files. "
                   "No model judgement is involved."),
        extra={"checks": checks, "cells": all_cells,
               "counts": {"display_equations": disp, "inline_math": inl,
                          "figures": figs, "citations": total_cites,
                          "body_chars": len(body)}},
        verifier="submission-shape")

    width = max(len(c["check"]) for c in checks)
    print(f"\nsubmission-shape on {a.workdir}\n" + "-" * (width + 60))
    for c in checks:
        print(f"  {'PASS' if c['pass'] else 'FAIL'}  {c['check']:<{width}}  {c['detail']}")
    print("-" * (width + 60))
    print(f"submission-shape: {verdict} -- {summary}")
    if failed and not a.warn_only:
        print("\nThe fix for a shape failure is almost never the prose. If n is too small "
              "or truncation is too high, re-run the experiment; if equations or figures "
              "are missing, the writer skipped a step.", file=sys.stderr)
    sys.exit(0 if (verdict != "FAIL" or a.warn_only) else 1)


if __name__ == "__main__":
    main()
