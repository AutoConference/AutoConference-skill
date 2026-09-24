#!/usr/bin/env python3
"""Draw a paper design and assemble the paper tree from it.

    python3 scripts/design_paper.py --seed 4127 --layout cvpr2 --evidence runs/
    python3 scripts/design_paper.py --seed 4127 --layout draw --evidence runs/ --dry-run
    python3 scripts/design_paper.py --seed 4127 --layout neurips1 --evidence runs/ \
        --prefer opening=results --prefer devices=principle

The contract is references/design-axes.md: seventeen axes, each value observed
in one of seven real papers, with hard constraints no draw violates and soft
pairings that weight the draw. The result is written to `paper.json` under
`design`, restated for the writer in `DESIGN-BRIEF.md`, and read by every
gate. Same seed, same evidence, same options -> same design.

Assembly copies the skill's template into `paper/`, overlays the drawn layout
(main.tex, preamble-layout.tex, the official style file) and copies each
drawn block to its canonical path. `paper/design.tex` carries the draw into
LaTeX as macros and switches that the blocks read.

Evidence-driven axes are decided from the aggregates, not drawn: the opening
figure needs enough conditions to plot, the radar needs five, a qualitative
figure needs at least two arms. `--prefer axis=value` overrides a draw, and
is refused when it breaks a hard constraint.
"""

from __future__ import annotations

import argparse
import json
import random
import shutil
import sys
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent
TEMPLATE = SKILL / "template"

LAYOUTS = ("neurips1", "iclr1", "cvpr2")

# Axis 14: the visual key. Each value is a published qualitative colour scheme,
# and each redefines the same semantic tokens, so the blocks never name a colour.
# Drawn from its own stream for the same reason the layout is: adding the axis
# must not shift what every earlier seed drew on the other thirteen.
PALETTES = ("ac-house", "okabe-ito", "tol-bright", "tol-muted", "brewer-dark2", "warm-ochre")

# Axis 15: the shape of the system figure. Every value is Tier C -- boxes,
# arrows, badges -- so it needs no artwork and never implies a magnitude. The
# family used to ship one form (three boxes, two arrows) in every paper.
OVERVIEWS = ("linear-pipeline", "stacked-panels", "wrap-compact",
             "arch-plus-flows", "mechanism-zoom")

# Axis 17: the glyph each of the five structural-figure roles is drawn with.
# Every name here has been VERIFIED TO RENDER, not merely to have a macro:
# fontawesome5 keeps deprecated aliases (\faExchange, \faShield) whose glyphs
# are absent from the Free set and which error at use, so \ifcsname is not a
# sufficient test. references/figure-icons.md is the same list for a writer,
# and check_paper_structure.py enforces it.
#
# The lists are role-scoped rather than one pool: a paper whose "output" glyph
# came out as a database reads as a mistake, and the point of drawing them is
# variety between papers, never surprise within one.
#
# PRUNED, after a batch of six papers drew two figures that said the wrong
# thing about their own contribution. A pool is not a list of glyphs that
# render; it is a list of glyphs that are DEFENSIBLE AS A DEFAULT, because
# whatever is in here lands on a paper nobody re-reads.
#
#   - "Magic" (a wand) drew onto a few-shot segmentation method. A wand on the
#     card labelled with the paper's own contribution tells a reviewer the
#     mechanism is unexplained.
#   - "Random" (a die) drew onto a contrastive objective, which is not random.
#   - "Burn" is a flame, and \acflame ALREADY means "updated during training"
#     in the same figure. Two meanings for one picture.
#   - Hammer/Wrench/Screwdriver/Tools/Brush/PenNib/Blender/Bullhorn read as
#     DIY, art supplies or advertising, never as a computational step.
#   - Trophy/Medal/Award/Certificate/Star on an OUTPUT card read as a
#     leaderboard brag; Gavel/Stamp/Signature read as officialdom. What is
#     produced and reported is a number, a decision or a file.
#   - Warehouse/Industry/Building/Desktop/Laptop/Hdd are premises and consumer
#     hardware, not a model backbone. BroadcastTower/SatelliteDish are right
#     only for a communications paper, which can still reach for them by hand.
#   - Barcode/Qrcode/Rss/Wifi/Envelope/Inbox are retail and messaging.
#
# Nothing here narrows what a WRITER may use: all 935 verified names stay
# legal and the gate still checks against the file. This is only what the
# draw reaches for unattended.
ICON_ROLES: dict[str, list[str]] = {
    # what enters the system
    "input": ["Database", "Atom", "Dna", "Image", "Images", "Film",
               "Video", "Camera", "Microphone", "Music", "Headphones",
               "Font", "Language", "Comment", "Comments", "Book",
               "BookOpen", "BookReader", "Newspaper", "File", "FileCode",
               "FileContract", "Folder", "FolderOpen", "Table", "Th",
               "ThList", "Archive", "Boxes", "Globe", "Map", "Users",
               "User", "Clipboard", "ClipboardList", "Stream", "Sitemap"],
    # the backbone every compared arm shares
    "model": ["ProjectDiagram", "Sitemap", "NetworkWired", "Microchip",
               "Cubes", "Cube", "LayerGroup", "Robot", "Brain", "Server",
               "CodeBranch", "Code", "Terminal", "Memory", "Boxes", "Cog",
               "Cogs", "Shapes"],
    # the mechanism this paper contributes
    "mech": ["Cogs", "BalanceScale", "Filter", "Compress", "Sort",
              "Stream", "Sync", "Key", "Lock", "Recycle", "SlidersH",
              "Bolt", "Cut", "Columns", "Retweet", "Eraser", "Highlighter",
              "Crop", "Adjust", "Clone", "Route", "Magnet", "Link",
              "Unlink", "Anchor", "Compass", "ObjectGroup", "ObjectUngroup",
              "VectorSquare", "BezierCurve", "Divide", "Equals", "Redo",
              "StepForward", "WaveSquare"],
    # what is produced and reported
    "out": ["Crosshairs", "Bullseye", "ChartBar", "ChartLine", "ChartPie",
             "ChartArea", "ClipboardCheck", "CheckCircle", "CheckDouble",
             "Flag", "Tag", "Bookmark", "FileExport", "ListOl",
             "SortAmountDown"],
    # the statistics or evidence the mechanism reads
    "evid": ["ChartBar", "ChartLine", "ChartArea", "ChartPie", "Flask",
              "Vial", "Vials", "Microscope", "Calculator", "Percent",
              "Stopwatch", "Weight", "WeightHanging", "Ruler",
              "RulerCombined", "Thermometer", "Table", "Poll", "PollH",
              "Binoculars", "Search"],
}

AXES: dict[str, list[str]] = {
    "opening": ["none", "results", "results-wide", "composite"],
    "contributions": ["bullets", "numbered", "inline", "none"],
    "related": ["themes-2", "themes-3", "subsections", "appendix"],
    "method_open": ["roadmap", "formal", "components", "preliminaries"],
    "equations": ["none", "sparse", "moderate", "dense", "sectioned"],
    "experiments": ["by-task", "setup-main-qual-ablation", "setup-ablation-sota",
                    "qual-quant-ablation", "bold-lead-stream", "roadmap-setup-results",
                    "separate-ablation-section"],
    "main_table": ["delta-rows", "plain-bold", "family-tint", "rank-colors",
                   "grouped-rules", "rotated-dense"],
    "ablation": ["none", "cumulative", "paired-minipage", "wo-rows", "default-delta",
                 "naive-vs-ours"],
    "qualitative": ["none", "distribution-lines", "small-multiples", "paired-scatter"],
    "appendix": ["none", "lettered", "deep", "supp-toc", "single"],
    "limitations": ["appendix", "conclusion-paragraph", "own-section", "absent"],
}
DEVICES = ["principle", "research-questions", "rhetorical-hook", "llm-usage",
           "symbols-table", "prior-limitations", "data-card", "efficiency-scatter"]

# Observed pairings (design-axes.md, "Soft"). A weight of 3 means "seen
# together in a real paper"; unlisted combinations weigh 1.
SOFT: list[tuple[str, str, str, str]] = [
    ("experiments", "by-task", "main_table", "delta-rows"),
    ("experiments", "qual-quant-ablation", "ablation", "wo-rows"),
    ("experiments", "qual-quant-ablation", "main_table", "grouped-rules"),
    ("experiments", "setup-ablation-sota", "ablation", "cumulative"),
    ("experiments", "setup-ablation-sota", "method_open", "roadmap"),
    ("experiments", "roadmap-setup-results", "main_table", "rotated-dense"),
    ("experiments", "roadmap-setup-results", "ablation", "default-delta"),
    ("experiments", "roadmap-setup-results", "method_open", "components"),
    ("experiments", "roadmap-setup-results", "related", "appendix"),
    ("experiments", "bold-lead-stream", "main_table", "plain-bold"),
    ("experiments", "bold-lead-stream", "appendix", "deep"),
    ("equations", "dense", "main_table", "family-tint"),
    ("equations", "dense", "experiments", "setup-main-qual-ablation"),
    ("equations", "sectioned", "main_table", "rank-colors"),
    ("equations", "sectioned", "ablation", "naive-vs-ours"),
    ("equations", "sectioned", "method_open", "preliminaries"),
    ("layout", "cvpr2", "opening", "results-wide"),
    ("layout", "neurips1", "contributions", "numbered"),
    ("layout", "iclr1", "related", "appendix"),
    ("layout", "iclr1", "equations", "none"),
    ("layout", "iclr1", "limitations", "own-section"),
]
SOFT_DEVICES: list[tuple[str, str, str]] = [
    ("experiments", "qual-quant-ablation", "research-questions"),
    ("experiments", "bold-lead-stream", "prior-limitations"),
    ("equations", "dense", "principle"),
    ("equations", "sectioned", "symbols-table"),
    ("equations", "sectioned", "efficiency-scatter"),
    ("experiments", "setup-ablation-sota", "data-card"),
    ("layout", "iclr1", "llm-usage"),
]

BUDGETS = {
    "single": {"00_abstract": (140, 260), "01_introduction": (420, 950),
               "02_related_work": (300, 650), "03_method": (1100, 2100),
               "04_experiments": (600, 1400), "05_conclusion": (130, 320),
               "_main_body": (3400, 5200), "_citations": 35},
    "double": {"00_abstract": (150, 260), "01_introduction": (500, 950),
               "02_related_work": (250, 600), "03_method": (1000, 1750),
               "04_experiments": (700, 1500), "05_conclusion": (120, 290),
               "_main_body": (3600, 4600), "_citations": 40},
}
APPENDIX_MIN = {"none": 0, "lettered": 800, "deep": 1500, "supp-toc": 2000, "single": 250}
EQ_FLOOR = {"none": 0, "sparse": 2, "moderate": 5, "dense": 9, "sectioned": 5}
CAPTION_BELOW = {"grouped-rules"}


# --------------------------------------------------------------------------- evidence
def read_evidence(evidence_dir: Path | None) -> dict:
    """What the aggregates can support. Counts, not values."""
    info = {"arms": 0, "conditions": 0, "primary": None, "metrics": [], "tier_a": False,
            "max_cond_len": 0}
    if evidence_dir is None or not evidence_dir.exists():
        return info
    aggs = sorted(evidence_dir.glob("aggregate__*.json"))
    methods, conds, metrics, primary = [], set(), [], None
    for p in aggs:
        try:
            a = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        m = a.get("method")
        if m and m not in methods:
            methods.append(m)
        conds |= set((a.get("per_split") or {}).keys())
        if a.get("metric") and a["metric"] not in metrics:
            metrics.append(a["metric"])
        if a.get("paired_contrast") and primary is None:
            primary = m
        if any(k in a for k in ("cost", "runtime", "latency")) or \
                any(k in (a.get("overall") or {}) for k in ("cost", "runtime", "latency")):
            info["has_cost"] = True
    info["max_cond_len"] = max((len(str(c)) for c in conds), default=0)
    info.update(arms=len(methods), conditions=len(conds), metrics=metrics,
                primary=primary or (methods[-1] if methods else None), methods=methods)
    return info


# --------------------------------------------------------------------------- constraints
def allowed(axis: str, design: dict, ev: dict) -> list[str]:
    vals = list(AXES[axis])
    layout = design.get("layout")
    if axis == "opening":
        if layout != "neurips1":               # composite is P3's single-column NeurIPS device
            vals = [v for v in vals if v != "composite"]
        if ev["conditions"] < 2 or ev["arms"] < 2:
            vals = ["none"]                     # nothing to plot honestly
    if axis == "ablation":
        if design.get("experiments") == "by-task":
            vals = ["none"]
        else:
            vals = [v for v in vals if v != "none"]
    if axis == "appendix":
        if design.get("equations") == "sectioned":
            vals = ["supp-toc"]
        if design.get("related") == "appendix":
            vals = [v for v in vals if v != "none"]
    if axis == "limitations" and design.get("appendix") == "none":
        vals = [v for v in vals if v != "appendix"]
    if axis == "equations" and (ev["conditions"] < 2 or ev["arms"] < 2):
        # with too little evidence for a second figure, the method has nothing
        # but prose left to carry it if the displays go too
        vals = [v for v in vals if v != "none"]
    if axis == "qualitative":
        if ev["conditions"] < 2 or ev["arms"] < 2:
            vals = ["none"]
        elif design.get("equations") == "none":
            # P6 is the only source paper with no numbered displays, and it
            # carries four figures. No paper of the seven drops the display
            # math AND the second figure: that leaves a main body of running
            # prose with nothing to break it, which is what "the paper feels
            # bare" looks like -- 2 floats over the first six pages.
            vals = [v for v in vals if v != "none"]
    return vals


def violates(design: dict) -> list[str]:
    """Hard constraints, stated once so --prefer can be refused with a reason."""
    bad = []
    L, E = design.get("layout"), design.get("evidence", {})
    if L == "cvpr2" and design.get("opening") == "composite":
        bad.append("composite opening is single-column only (P3)")
    if design.get("opening") == "composite" and L != "neurips1":
        bad.append("composite opening requires layout=neurips1 (P3)")
    if (design.get("experiments") == "by-task") != (design.get("ablation") == "none"):
        bad.append("by-task experiments <=> ablation=none (P1)")
    if design.get("equations") == "sectioned" and design.get("appendix") != "supp-toc":
        bad.append("sectioned equations require appendix=supp-toc (P4)")
    if design.get("related") == "appendix" and design.get("appendix") == "none":
        bad.append("related=appendix needs an appendix to live in")
    if design.get("limitations") == "appendix" and design.get("appendix") == "none":
        bad.append("limitations=appendix needs an appendix")
    if design.get("opening") in {"results", "results-wide", "composite"} and \
            (E.get("conditions", 0) < 2 or E.get("arms", 0) < 2):
        bad.append("a quantitative opening needs >=2 arms and >=2 conditions in the evidence")
    if design.get("equations") == "none" and design.get("qualitative") == "none":
        bad.append("equations=none with qualitative=none leaves no display math and no "
                   "second figure; P6, the one source paper without displays, carries four figures")
    if "llm-usage" in design.get("devices", []) and L != "iclr1":
        bad.append("llm-usage is an ICLR section (P6)")
    return bad


def weighted_choice(rng: random.Random, axis: str, values: list[str], design: dict) -> str:
    weights = []
    for v in values:
        w = 1.0
        for a1, v1, a2, v2 in SOFT:
            if a2 == axis and v2 == v and design.get(a1) == v1:
                w *= 3.0
            if a1 == axis and v1 == v and design.get(a2) == v2:
                w *= 3.0
        weights.append(w)
    return rng.choices(values, weights=weights, k=1)[0]


def draw(seed: int, layout: str, ev: dict, prefer: dict[str, str]) -> dict:
    rng = random.Random(seed)
    design: dict = {"seed": seed, "evidence": ev}
    # The layout is drawn from its own stream, so `--layout draw` and a pinned
    # `--layout X` agree on every other axis for the same seed (an early draw
    # from the shared stream would shift everything after it).
    design["layout"] = layout if layout != "draw" else random.Random(seed * 7919 + 17).choice(LAYOUTS)
    design["palette"] = random.Random(seed * 104729 + 31).choice(PALETTES)
    # a wrapfigure inside a CVPR column leaves neither the figure nor the text
    # enough width; P3 and P6, the two papers that use one, are both single-column
    ov = [o for o in OVERVIEWS if not (o == "wrap-compact" and design["layout"] == "cvpr2")]
    design["overview"] = random.Random(seed * 15485863 + 7).choice(ov)
    # P1, P3, P7 carry a project mark beside the title; P2 and P5 carry none
    design["mark"] = random.Random(seed * 611953 + 13).random() < 0.55
    # Axis 17: one glyph per role, each from its own stream, so changing the
    # seed moves them independently of the palette and of each other. Roles
    # that can legitimately share a glyph (out and evid both allow ChartBar)
    # are forced apart -- the same icon twice in one figure reads as a link
    # between two stages that are not linked.
    icons: dict[str, str] = {}
    for n, role in enumerate(("input", "model", "mech", "out", "evid")):
        pool = [g for g in ICON_ROLES[role] if g not in icons.values()]
        icons[role] = random.Random(seed * (32452843 + 7 * n) + 101 + n).choice(pool)
    design["icons"] = icons
    if "palette" in prefer:
        if prefer["palette"] not in PALETTES:
            sys.exit(f"--prefer palette={prefer['palette']}: not a palette "
                     f"(choose from {', '.join(PALETTES)})")
        design["palette"] = prefer["palette"]
    if "overview" in prefer:
        if prefer["overview"] not in OVERVIEWS:
            sys.exit(f"--prefer overview={prefer['overview']}: not an overview grammar "
                     f"(choose from {', '.join(OVERVIEWS)})")
        if prefer["overview"] == "wrap-compact" and design["layout"] == "cvpr2":
            sys.exit("--prefer overview=wrap-compact: a wrapfigure needs a single-column layout")
        design["overview"] = prefer["overview"]
    if "layout" in prefer:
        if prefer["layout"] not in LAYOUTS:
            sys.exit(f"--prefer layout={prefer['layout']}: not a layout "
                     f"(choose from {', '.join(LAYOUTS)})")
        design["layout"] = prefer["layout"]
    # Order matters: later axes are conditioned on earlier ones.
    order = ["experiments", "equations", "opening", "contributions", "related",
             "method_open", "main_table", "ablation", "qualitative", "appendix", "limitations"]
    for axis in order:
        vals = allowed(axis, design, ev)
        if axis in prefer:
            if axis == "opening" and prefer[axis] == "design-card":
                design[axis] = "design-card"      # operator-only fallback, never drawn
                continue
            if prefer[axis] not in AXES[axis]:
                sys.exit(f"--prefer {axis}={prefer[axis]}: not a value of that axis "
                         f"(choose from {AXES[axis]})")
            design[axis] = prefer[axis]
        else:
            design[axis] = weighted_choice(rng, axis, vals, design)
    # devices: 0-2, weighted by pairings, never llm-usage outside iclr1
    pool = [d for d in DEVICES if not (d == "llm-usage" and design["layout"] != "iclr1")
            and not (d == "efficiency-scatter" and not ev.get("has_cost"))]
    weights = []
    for d in pool:
        w = 1.0
        for a1, v1, dev in SOFT_DEVICES:
            if dev == d and design.get(a1) == v1:
                w *= 3.0
        weights.append(w)
    k = rng.choices([0, 1, 2], weights=[1, 3, 2], k=1)[0]
    chosen: list[str] = []
    for _ in range(k):
        d = rng.choices(pool, weights=weights, k=1)[0]
        if d not in chosen:
            chosen.append(d)
    if "devices" in prefer:
        chosen = [d for d in prefer["devices"].split("+") if d]
        unknown = [d for d in chosen if d not in DEVICES]
        if unknown:
            sys.exit(f"--prefer devices: unknown {unknown}; choose from {DEVICES}")
    design["devices"] = chosen
    design["table_caption"] = "below" if design["main_table"] in CAPTION_BELOW else "above"
    design["equation_floor"] = EQ_FLOOR[design["equations"]]
    cols = "double" if design["layout"] == "cvpr2" else "single"
    design["budgets"] = {**BUDGETS[cols], "06_appendix": (APPENDIX_MIN[design["appendix"]], 20000)}
    # a radar beside the bars needs the full text width; in a two-column
    # layout only the results-wide slot has it (S26: a column is too tight)
    # The radar prints every condition name around its circumference and it
    # halves the bar panel's width, so long condition names collide twice over:
    # once on the radar's own rim and once among the bar panel's rotated ticks.
    # Measured: names up to 12 characters fit both; "objects365-shift" does not.
    design["radar"] = (ev.get("conditions", 0) >= 5 and design["opening"] != "none"
                       and ev.get("max_cond_len", 0) <= 12
                       and not (design["layout"] == "cvpr2" and design["opening"] == "results"))
    problems = violates(design)
    if problems:
        sys.exit("the requested design violates a hard constraint:\n  - " + "\n  - ".join(problems))
    return design


# --------------------------------------------------------------------------- assembly
def copy_tree_excluding(src: Path, dst: Path, exclude: set[str]) -> None:
    for p in src.rglob("*"):
        rel = p.relative_to(src)
        if rel.parts and rel.parts[0] in exclude:
            continue
        target = dst / rel
        if p.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, target)


def block(path: str) -> Path:
    p = TEMPLATE / "blocks" / path
    if not p.exists():
        sys.exit(f"block not found: {p} (the family is incomplete; see design-axes.md)")
    return p


def write_design_tex(design: dict, out: Path) -> None:
    d = design
    tex = [
        "% GENERATED by scripts/design_paper.py. Do not edit by hand; re-run with the",
        "% same seed to regenerate. Carries the drawn design into LaTeX so that the",
        "% blocks and the layout can read it.",
        f"\\def\\DesignLayout{{{d['layout']}}}",
        f"\\def\\DesignOpening{{{d['opening']}}}",
        f"\\def\\DesignMainTable{{{d['main_table']}}}",
        f"\\def\\DesignAblation{{{d['ablation']}}}",
        f"\\def\\DesignSeed{{{d['seed']}}}",
        "\\newif\\ifDesignTwoColumn" + ("\\DesignTwoColumntrue" if d["layout"] == "cvpr2" else "\\DesignTwoColumnfalse"),
        "\\newif\\ifDesignAuthorYear" + ("\\DesignAuthorYeartrue" if d["layout"] == "iclr1" else "\\DesignAuthorYearfalse"),
        "\\newif\\ifOPradar" + ("\\OPradartrue" if d.get("radar") else "\\OPradarfalse"),
        "\\newif\\ifDesignSectionedEq" + ("\\DesignSectionedEqtrue" if d["equations"] == "sectioned" else "\\DesignSectionedEqfalse"),
        "\\newif\\ifDesignAppendix" + ("\\DesignAppendixtrue" if d["appendix"] != "none" else "\\DesignAppendixfalse"),
        # declared with a default in preamble.tex; only the false case is written
        ("" if d.get("mark", True) else "\\DesignMarkfalse"),
        "",
        "% --- the structural figure's five glyphs (axis 17) ----------------------",
        "% A writer whose domain wants a different glyph renews one of these in",
        "% macros.tex, choosing from references/figure-icons.md. Nothing else in",
        "% the paper has to change: every overview grammar reads these macros.",
        f"\\renewcommand{{\\acIconInput}}{{{d.get('icons', {}).get('input', 'Database')}}}",
        f"\\renewcommand{{\\acIconModel}}{{{d.get('icons', {}).get('model', 'ProjectDiagram')}}}",
        f"\\renewcommand{{\\acIconMech}}{{{d.get('icons', {}).get('mech', 'Cogs')}}}",
        f"\\renewcommand{{\\acIconOut}}{{{d.get('icons', {}).get('out', 'Crosshairs')}}}",
        f"\\renewcommand{{\\acIconEvid}}{{{d.get('icons', {}).get('evid', 'ChartBar')}}}",
        "",
        "% --- best-value markers, rendered per the drawn table grammar ------------",
        "% The gate checks the marker (\\best, \\second, \\rankone ...), never the",
        "% rendering, so a grammar may draw them however its source paper does.",
    ]
    mt = d["main_table"]
    if mt == "rotated-dense":          # P6: best is underlined, second is plain
        tex += ["\\renewcommand{\\best}[1]{\\underline{#1}}",
                "\\renewcommand{\\second}[1]{#1}"]
    else:
        tex += ["\\renewcommand{\\best}[1]{\\textbf{#1}}",
                "\\renewcommand{\\second}[1]{\\underline{#1}}"]
    tex += [
        "\\renewcommand{\\rankone}[1]{\\cellcolor{ACRankOne}#1}",
        "\\renewcommand{\\ranktwo}[1]{\\cellcolor{ACRankTwo}#1}",
        "\\renewcommand{\\rankthree}[1]{\\cellcolor{ACRankThree}#1}",
        "\\renewcommand{\\worse}[1]{\\textcolor{ACWorse}{#1}}",
        "\\renewcommand{\\deltarow}[1]{\\textcolor{ACGreen}{\\textbf{#1}}}",
        "\\renewcommand{\\deltacell}[1]{{\\tiny\\ \\textcolor{ACDelta}{(#1)}}}",
        "\\renewcommand{\\rothead}[1]{\\rotatebox{90}{\\textbf{#1}}}",
        "",
    ]
    if d["equations"] == "sectioned":
        tex += ["\\numberwithin{equation}{section}",
                "\\usepackage{algorithm}", "\\usepackage{algpseudocode}", ""]
    out.write_text("\n".join(tex) + "\n", encoding="utf-8")


def assemble(design: dict, project: Path, force: bool) -> None:
    paper = project / "paper"
    if paper.exists():
        if not force:
            sys.exit(f"{paper} exists; pass --force to replace it (this discards its contents)")
        shutil.rmtree(paper)
    copy_tree_excluding(TEMPLATE, paper, exclude={"layouts", "blocks"})
    L = design["layout"]
    layout_dir = TEMPLATE / "layouts" / L
    if not layout_dir.exists():
        sys.exit(f"layout not found: {layout_dir}")
    wide = design["opening"] in {"results-wide", "composite"}
    main_variant = "main-wide.tex" if (L == "cvpr2" and wide) else "main.tex"
    shutil.copy2(layout_dir / main_variant, paper / "main.tex")
    shutil.copy2(layout_dir / "preamble-layout.tex", paper / "preamble-layout.tex")
    for sty in layout_dir.glob("*.sty"):
        shutil.copy2(sty, paper / sty.name)
    for bst in layout_dir.glob("*.bst"):
        shutil.copy2(bst, paper / bst.name)
    (paper / "blocks").mkdir(exist_ok=True)

    shutil.copy2(block(f"palettes/{design.get('palette', 'ac-house')}.tex"), paper / "palette.tex")
    if design.get("overview"):
        shutil.copy2(block(f"overview/{design['overview']}.tex"), paper / "figures/method_overview.tex")
    shutil.copy2(block(f"opening/{design['opening']}.tex"), paper / "figures/opening.tex")
    shutil.copy2(block("opening_panel.tex"), paper / "blocks/opening_panel.tex")
    shutil.copy2(block(f"contributions/{design['contributions']}.tex"), paper / "blocks/contributions.tex")
    shutil.copy2(block(f"related/{design['related']}.tex"), paper / "sections/02_related_work.tex")
    shutil.copy2(block(f"method-open/{design['method_open']}.tex"), paper / "blocks/method_open.tex")
    shutil.copy2(block(f"experiments/{design['experiments']}.tex"), paper / "sections/04_experiments.tex")
    if design["experiments"] == "separate-ablation-section":
        shutil.copy2(block("experiments/04b_ablation_section.tex"), paper / "sections/04b_ablation.tex")
    shutil.copy2(block(f"tables/{design['main_table']}.tex"), paper / "tables/main_results.tex")
    shutil.copy2(block(f"ablation/{design['ablation']}.tex"), paper / "tables/ablations.tex")
    shutil.copy2(block(f"qualitative/{design['qualitative']}.tex"), paper / "figures/results_panel.tex")
    shutil.copy2(block(f"appendix/{design['appendix']}.tex"), paper / "sections/06_appendix.tex")
    if design["related"] == "appendix":
        with (paper / "sections/06_appendix.tex").open("a", encoding="utf-8") as fh:
            fh.write("\n" + block("related/appendix-full.tex").read_text(encoding="utf-8"))
    shutil.copy2(block(f"limitations/{design['limitations']}.tex"), paper / "blocks/limitations.tex")
    dev_lines = ["% GENERATED: the devices this design draws. Each snippet documents itself."]
    for dev in design["devices"]:
        p = TEMPLATE / "blocks" / "devices" / f"{dev}.tex"
        if p.exists():
            dev_lines.append(p.read_text(encoding="utf-8"))
    (paper / "blocks/devices.tex").write_text("\n".join(dev_lines) + "\n", encoding="utf-8")
    if design["equations"] == "sectioned":
        shutil.copy2(block("devices/algorithm-float.tex"), paper / "blocks/algorithm.tex")
    if design["opening"] != "design-card":
        # the legacy card and its numeric macros are dead code for every other
        # opening; leaving them in place puts unfillable \slot{}s in the tree
        for dead in ("figures/hero.tex", "data/teaser.tex"):
            (paper / dead).unlink(missing_ok=True)
    write_design_tex(design, paper / "design.tex")
    # the old hero stays available as the documented fallback, nothing inputs it
    # unless opening=design-card was forced by the operator


def write_brief(design: dict, project: Path) -> None:
    d = design
    ev = d["evidence"]
    two = d["layout"] == "cvpr2"
    L = {
        "neurips1": "NeurIPS single column: thick rule above the title, bold headings, numeric [n] citations.",
        "iclr1": "ICLR single column: small-caps headings, running header, author-year citations (\\citep / \\citet). An `LLM Usage` section is allowed.",
        "cvpr2": "CVPR two columns: plain title block, italic abstract, numeric citations. Full-width floats are figure* / table*.",
    }[d["layout"]]
    OP = {
        "none": "No opening figure. The abstract and §1 start on page 1. The overview figure must appear by page 4.",
        "results": ("A numbered, captioned quantitative panel (P1's grammar): grouped bars per condition, the primary arm's "
                    "delta over the strongest baseline annotated above each bar" + (", plus a radar panel" if d.get("radar") else "") +
                    (". Column width, floats to the top of a column." if two else ". Full width, right after the title block.")),
        "results-wide": "The same quantitative panel, full width above the abstract (P2/P7's position" + (", the \\twocolumn[] slot" if two else "") + ").",
        "composite": "P3's grammar: unnumbered, uncaptioned, full width. Left: a Tier-C worked instance of the task (one input → the method → its output, no magnitudes). Right: the results panel. Fill figures/opening.tex's instance box with the study's own case.",
        "design-card": "The fallback Question/Design/Finding card. Only because the evidence cannot support a plot.",
    }[d["opening"]]
    CO = {"bullets": "plain bullets, one falsifiable sentence each",
          "numbered": "an itemize with \\item[\\textbf{(1)}] markers",
          "inline": "one paragraph, contributions run in as bold (1), (2), (3)",
          "none": "no list — 'Our key contribution is …' stated inline in the last intro paragraph"}[d["contributions"]]
    RE = {"themes-2": "two bold inline themes, one dense paragraph each, each ending by positioning this paper",
          "themes-3": "three bold inline themes, then a closing scope paragraph",
          "subsections": "numbered \\subsections, one per line of work, each ending by positioning this paper",
          "appendix": "ONE paragraph in the main body naming the families and pointing to the appendix; the full section is appendix A"}[d["related"]]
    MO = {"roadmap": "a roadmap paragraph: 'Sec. 3.1 introduces … Sec. 3.2 … Sec. 3.3 …', then the subsections",
          "formal": "the formal problem statement inline: 'Given X … the goal is to produce Y', with notation",
          "components": "a numbered list of the method's components with \\texttt{monospace} names, one sentence each",
          "preliminaries": "a first subsection restating the prior framework the method builds on"}[d["method_open"]]
    EQ = {"none": "no numbered displays; all math inline (P6). The overview figure and prose carry the method.",
          "sparse": "about four numbered displays, each with one `where` sentence",
          "moderate": "five to eight numbered displays, each narrated",
          "dense": "nine to twelve numbered displays, the full narration sandwich, possibly a Principle device",
          "sectioned": "section-prefixed numbers (\\numberwithin is set), key results in \\boxed{}, and one algorithm float (blocks/algorithm.tex)"}[d["equations"]]
    EX = {"by-task": "Setup, then ONE SUBSECTION PER TASK/CONDITION FAMILY, each with its own table and prose. No ablation section (P1).",
          "setup-main-qual-ablation": "Setup → Main results → Qualitative/distributional analysis → Ablations (P3).",
          "setup-ablation-sota": "Setup → Ablation study (argued figure-first, one cumulative table last) → Comparison with state of the art (P2).",
          "qual-quant-ablation": "Open with a bullet list of 'How …?' research questions each pointing at a subsection, then Setup → Qualitative → Quantitative → Ablation (P7).",
          "bold-lead-stream": "Setup, then one long Results subsection of bold-lead paragraphs (some leads end in a colon), reading tables in order (P5).",
          "roadmap-setup-results": "A roadmap paragraph, then 4–7 subsections each shaped as 'Evaluation Setup.' / 'Results.' (P6).",
          "separate-ablation-section": "Experiments = Setup + Comparison; then a TOP-LEVEL 'Ablation Study' section with 3–4 one-question subsections (P4)."}[d["experiments"]]
    MT = {"delta-rows": "baseline rows, then ours, then a bold green Δ row with explicit + signs (\\deltarow); one vertical rule after the overall column; NO bold cells",
          "plain-bold": "plain booktabs, \\best on the winning cell, no tints",
          "family-tint": "rows tinted by family, \\best bold and \\second underline, swatches introduced in prose",
          "rank-colors": "\\rankone / \\ranktwo / \\rankthree cell backgrounds for 1st/2nd/3rd, ✓/✗ property columns, Type multirow groups",
          "grouped-rules": "two-level header with vertical rules between groups only, per-column \\up/\\down, \\best/\\second, CAPTION BELOW the table",
          "rotated-dense": "rotated column headers (\\rothead), \\best renders as UNDERLINE, scores worse than ours wrapped in \\worse{}, 7pt"}[d["main_table"]]
    AB = {"none": "no ablation table",
          "cumulative": "rows Baseline / + A / + A&B / … / Ours (bold): one build-up",
          "paired-minipage": "two small tables side by side, metrics as rows, the swept setting as columns",
          "wo-rows": "Full first, then w/o A, w/o B, … with the same metric columns as the main table",
          "default-delta": "the default row tinted; every other cell carries \\deltacell{±δ}",
          "naive-vs-ours": "two-level header Naive | Ours over the same metrics"}[d["ablation"]]
    QU = {"none": "no secondary figure (P5, P6): the tables carry the evidence",
          "distribution-lines": "per-condition means as lines, one per arm, the primary arm's spread as a band",
          "small-multiples": "one small panel per condition, arms as bars (groupplot)",
          "paired-scatter": "per-condition points, primary vs strongest baseline, with the diagonal"}[d["qualitative"]]
    AP = {"none": "no appendix; the paper ends at the references",
          "lettered": "lettered sections A–… in the PDF, ≥800 words",
          "deep": "lettered sections; every further study as X.1 Experimental setting. / X.2 Experimental details. / X.3 Analysis. (≥1500 words)",
          "supp-toc": "a supplementary title page with \\tableofcontents, then lettered sections incl. theorem-style derivations and a symbols table (≥2000 words)",
          "single": "one appendix section (≥250 words)"}[d["appendix"]]
    LI = {"appendix": "a lettered appendix section",
          "conclusion-paragraph": "a bold-lead 'Limitations.' paragraph closing the conclusion",
          "own-section": "an unnumbered Limitations section after the conclusion",
          "absent": "not stated"}[d["limitations"]]
    DV = {"principle": "Principle N device in the method (bold label + italic one-sentence rule + evidence paragraph), at most twice",
          "research-questions": "bullet list of research questions opening Experiments, each → its subsection",
          "rhetorical-hook": "the introduction opens with a question addressed to the reader",
          "llm-usage": "an unnumbered LLM Usage section after the conclusion",
          "symbols-table": "a symbols table in the appendix",
          "prior-limitations": "numbered bold limitations of prior work in the introduction, before the proposal",
          "data-card": "a tiny dataset-statistics table with ✓/× cells in the setup",
          "efficiency-scatter": "a quality-vs-cost scatter as the second figure (blocks/devices.tex has the skeleton)"}
    OV = {"linear-pipeline": "numbered stages left to right, a dashed box around the stages that differ across arms, frozen / trained badges. Full width, first float of the Method section.",
          "stacked-panels": "a pipeline row, then two titled sub-panels (a) and (b) opening up the two components this paper contributes (P2). Its caption is a paragraph that walks the panels in order, not a phrase.",
          "wrap-compact": "a narrow wrapfigure the body text flows around (P3, P6), with a short caption. Do not widen it; the point is that the method reads as prose with a sketch beside it.",
          "arch-plus-flows": "left, the architecture as a vertical stack; right, the two or three ways the trained object is used, numbered (P6).",
          "mechanism-zoom": "the pipeline row, and under it a zoom into the one module this paper contributes, with what it receives, does and emits (P7)."}[d.get("overview", "linear-pipeline")]
    b = d["budgets"]
    lines = [
        f"# Design brief — seed {d['seed']}",
        "",
        "Generated by `scripts/design_paper.py`. This is the shape this paper takes.",
        "Follow it; the gates check the manuscript against exactly this draw",
        "(`paper.json` → `design`). Prose, evidence, citations and the figure ladder",
        "are governed by the usual references; this file only fixes the design.",
        "",
        f"- **Layout**: `{d['layout']}` — {L}"
        + ("" if d["layout"] != "neurips1" else
           f" A project mark sits left of the title: {'yes' if d.get('mark', True) else 'no, the title starts at the margin (P2, P5)'}."),
        f"- **System figure**: `{d.get('overview', 'linear-pipeline')}` — {OV} It is Tier C: "
        "boxes, arrows and labels only, no magnitudes and no stand-in for artwork that does not exist.",
        f"- **Palette**: `{d.get('palette', 'ac-house')}` — in `paper/palette.tex`. Every block reads "
        "semantic tokens (`ACBlue` = this paper's arm, `ACPrimary` = its row tint, `ACGreen` / `ACWorse` "
        "= a delta in the good / bad direction). Never write a literal colour into a float, and never "
        "let colour be the only cue: the marker macros and the \\up / \\down arrows carry the meaning.",
        f"- **Opening (page 1)**: `{d['opening']}` — {OP}",
        f"- **Contributions**: `{d['contributions']}` — {CO}",
        f"- **Related work**: `{d['related']}` — {RE}",
        f"- **Method opening**: `{d['method_open']}` — {MO}",
        f"- **Equation register**: `{d['equations']}` — {EQ} (gate floor: {d['equation_floor']} numbered displays)",
        f"- **Experiments**: `{d['experiments']}` — {EX}",
        f"- **Main table**: `{d['main_table']}` — {MT}",
        f"- **Ablation**: `{d['ablation']}` — {AB}",
        f"- **Secondary figure**: `{d['qualitative']}` — {QU}",
        f"- **Appendix**: `{d['appendix']}` — {AP}",
        f"- **Limitations**: `{d['limitations']}` — {LI}",
        "- **Devices**: " + (", ".join(f"`{x}` — {DV[x]}" for x in d["devices"]) if d["devices"] else "none"),
        "",
        "## Word envelopes for this layout",
        "",
        "| section | words |", "|---|---|",
    ] + [f"| {k} | {v[0]}–{v[1]} |" for k, v in b.items() if not k.startswith("_") and k != "06_appendix"] + [
        f"| main body | {b['_main_body'][0]}–{b['_main_body'][1]} |",
        f"| appendix | ≥ {b['06_appendix'][0]} |",
        f"| main-body \\cite calls | ≥ {b['_citations']} |",
        "",
        "## Evidence this design was drawn against",
        "",
        f"- arms: {ev.get('arms')} ({', '.join(ev.get('methods', []) or [])})",
        f"- conditions: {ev.get('conditions')}   primary arm: {ev.get('primary')}",
        f"- radar panel: {'yes' if d.get('radar') else 'no'}",
        "",
        "## Files this draw put in place",
        "",
        "```",
        "paper/main.tex                     the layout's main file (do not restructure)",
        "paper/preamble-layout.tex          layout-specific packages",
        "paper/design.tex                   GENERATED switches and markers; never edit",
        "paper/figures/opening.tex          the opening figure block",
        "paper/blocks/contributions.tex     \\begin{contributionlist} / \\contribution{}",
        "paper/blocks/method_open.tex       the method's opening move (input at the top of 03_method.tex)",
        "paper/blocks/limitations.tex       \\LimitationsBlock, rendered where the design says",
        "paper/blocks/devices.tex           snippets for the drawn devices",
        "paper/sections/02_related_work.tex the related-work skeleton for this organization",
        "paper/sections/04_experiments.tex  the experiments skeleton for this organization",
        "paper/tables/main_results.tex      the main table in this grammar",
        "paper/tables/ablations.tex         the ablation table in this grammar",
        "paper/figures/results_panel.tex    the secondary figure in this grammar",
        "paper/sections/06_appendix.tex     the appendix scaffold",
        "```",
        "",
        "Data for the opening and secondary figures:",
        "",
        "```",
        f"python3 <skill>/scripts/make_paper_data.py --config paper.json --opening runs/aggregate__*.json --primary {ev.get('primary') or '<method>'}",
        "```",
        "",
        "Then fill every \\slot{} from the aggregates and run `<skill>/scripts/gate.sh` from this",
        "directory (it builds, renders, and runs every checker with the budget above). Fix every",
        "ERROR, re-run; do not iterate on ADVISORY items. Then look at the rendered pages.",
    ]
    (project / "DESIGN-BRIEF.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------- main
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--layout", default="draw", choices=list(LAYOUTS) + ["draw"])
    ap.add_argument("--evidence", type=Path, default=Path("runs"), help="directory of aggregate__*.json")
    ap.add_argument("--project", type=Path, default=Path("."), help="project root (holds paper.json, paper/)")
    ap.add_argument("--prefer", action="append", default=[], metavar="AXIS=VALUE",
                    help="override one axis; devices as devices=a+b")
    ap.add_argument("--dry-run", action="store_true", help="print the draw, write nothing")
    ap.add_argument("--force", action="store_true", help="replace an existing paper/")
    args = ap.parse_args()

    prefer: dict[str, str] = {}
    for item in args.prefer:
        if "=" not in item:
            ap.error(f"--prefer expects AXIS=VALUE, got {item!r}")
        k, v = item.split("=", 1)
        if k not in AXES and k not in {"layout", "devices", "palette", "overview"}:
            ap.error(f"unknown axis {k!r}; axes: {', '.join(list(AXES) + ['layout', 'devices'])}")
        prefer[k] = v

    ev = read_evidence(args.evidence)
    design = draw(args.seed, args.layout, ev, prefer)

    summary = {k: v for k, v in design.items() if k not in {"budgets", "evidence"}}
    print(json.dumps(summary, indent=2))
    if args.dry_run:
        return 0

    project = args.project.resolve()
    project.mkdir(parents=True, exist_ok=True)
    cfg_path = project / "paper.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8")) if cfg_path.exists() else \
        json.loads((SKILL / "config.example.json").read_text(encoding="utf-8"))
    cfg["design"] = design
    cfg.setdefault("venue", {})
    cfg["venue"]["style"] = {"neurips1": "neurips_2025.sty", "iclr1": "iclr2026_conference.sty",
                             "cvpr2": "cvpr.sty"}[design["layout"]]
    cfg["venue"]["name"] = {"neurips1": "NeurIPS 2025", "iclr1": "ICLR 2026", "cvpr2": "CVPR 2026"}[design["layout"]]
    cfg["venue"]["max_main_pages"] = 8 if design["layout"] == "cvpr2" else 9
    assemble(design, project, args.force)
    cfg_path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    write_brief(design, project)
    print(f"assembled {project / 'paper'} for layout {design['layout']}; wrote paper.json and DESIGN-BRIEF.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
