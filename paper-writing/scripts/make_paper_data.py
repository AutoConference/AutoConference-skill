#!/usr/bin/env python3
"""Generate the paper's data files from aggregation artifacts.

This is the only path by which a number reaches the manuscript. The teaser
macros, the opening-figure data, and the plot data are written from the same
aggregates that fill the tables, so a plotted value and a tabled value cannot
disagree.

    python3 scripts/make_paper_data.py --opening runs/aggregate__*.json --primary ours
    python3 scripts/make_paper_data.py --figure distribution runs/aggregate__*.json
    python3 scripts/make_paper_data.py --teaser runs/aggregate__*.json \
        --question "..." --finding "..."
    python3 scripts/make_paper_data.py --table-stats runs/aggregate__*.json \
        --precision 1

--opening writes everything the opening figure and the secondary figures of
the design family read (references/design-axes.md axes 2 and 10):

    paper/data/opening.dat               cond arm1..armN delta lo hi
    paper/data/opening.tex               \\OPnarms \\OPnconds \\OPmetric ... (macros)
    paper/data/opening-series.tex        \\addplot lines for the bar panel
    paper/data/opening-lines.tex         \\addplot lines for distribution-lines
    paper/data/opening-multiples.tex     groupplot body for small-multiples
    paper/data/opening-pairs.dat         cond base primary   (paired-scatter)
    paper/data/opening-radar.dat + opening-radar-series.tex  (>= 5 conditions)

The primary arm is named with --primary; every other arm is a comparison arm.
The delta annotated above each primary bar is the primary arm's margin over
the strongest other arm in that condition, signed so that positive is better
under --direction (up: higher is better, the default; down: lower is better).

--table-stats writes paper/data/table_stats.tex, a COMMENT-ONLY reference
(never \\input -- there is no script that lays out a table's bespoke
multirow/rotated-header/grouped-rule structure, so the table itself stays
hand-authored, same as before). What this closes is the gap between the
figure path and the table path: --opening already computes a `lo`/`hi` band
for the primary arm from per_split[cond]['values'], but only for the primary
arm, and only shaped for pgfplots. A table's uncertainty convention
(references/table-grammar.md, "Reporting uncertainty") needs the SAME min/max
for every arm, addressed by method name rather than by plot series index, so
it prints one line per (method, condition) as `mean [lo, hi]` at a shared
precision, ready to paste into a table cell. It is still hand-transcription
-- the same discipline every real table's "generator:" comment already
documents -- just against pre-computed, precision-matched text instead of
mental arithmetic over the raw JSON. Cite this file in the table's own
"generator:" comment when you use it, exactly as the mean's source is cited
today.

Two aggregates may share a `method` when they report different metrics
(one file per metric per arm). Pass --metric to say which one the figures
read; without it, a shared method name across different metrics is an error
rather than a silent choice of whichever file sorts last.

Refuses to write anything when an aggregate is missing a field, does not
enumerate its primary inputs, or points at a primary run that is not on disk.
A missing data file is a correct outcome: the figure blocks are guarded with
\\IfFileExists, so a float and its narrating sentence simply do not appear
until real values exist.

Expected aggregate schema (written by the aggregation step, not by hand):

    {
      "label":        "random-vs-maxerror",
      "method":       "random",
      "metric":       "p2l_bound",
      "estimator":    "mean over trajectory seeds, per split seed",
      "primary_inputs": ["runs/<label>__<commit>.json", ...],
      "per_split": {
        "1": {"mean": 0.379, "std": 0.021, "n": 3,
              "values": [0.371, 0.379, 0.387]},
        ...
      },
      "overall":     {"mean": 0.381, "std": 0.024, "range": 0.062, "n_splits": 5},
      "paired_contrast": {"mean": -0.031, "uncertainty": 0.009, "against": "max-error"}
    }
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

REQUIRED = ("label", "method", "metric", "estimator", "primary_inputs", "per_split", "overall")

# Series colors, primary first. Names are preamble.tex palette entries.
PRIMARY_COLOR = "ACBlue"
OTHER_COLORS = ["ACMuted", "ACCompare!70!black", "ACCyan!80!black", "ACGreen", "BrickRed!70", "ACInk!60"]


def load(paths: list[Path]) -> list[dict]:
    aggregates = []
    for path in paths:
        if not path.exists():
            sys.exit(f"aggregate not found: {path}")
        data = json.loads(path.read_text(encoding="utf-8"))
        missing = [k for k in REQUIRED if k not in data]
        if missing:
            sys.exit(f"{path}: aggregate is missing required field(s) {missing}; "
                     "a derived number cannot certify itself")
        if not data["primary_inputs"]:
            sys.exit(f"{path}: aggregate enumerates no primary inputs")
        for raw in data["primary_inputs"]:
            if not Path(raw).exists():
                sys.exit(f"{path}: primary input '{raw}' is not on disk; "
                         "the claim it supports cannot be cited")
        data["_path"] = str(path)
        aggregates.append(data)
    return aggregates


def select_metric(aggregates: list[dict], metric: str | None) -> list[dict]:
    """One aggregate per method. A method with several metrics needs --metric."""
    metrics = sorted({a["metric"] for a in aggregates})
    if metric is None:
        if len(metrics) > 1:
            by_method: dict[str, set[str]] = {}
            for a in aggregates:
                by_method.setdefault(a["method"], set()).add(a["metric"])
            clashes = {m: sorted(v) for m, v in by_method.items() if len(v) > 1}
            if clashes:
                sys.exit("several aggregates share a method name but report different metrics: "
                         f"{clashes}. Pass --metric <name> to say which one the figures read; "
                         "picking whichever file sorts last would silently substitute one "
                         "metric's values for another's.")
        chosen = aggregates
    else:
        chosen = [a for a in aggregates if a["metric"] == metric]
        if not chosen:
            sys.exit(f"no aggregate reports metric '{metric}' (available: {metrics})")
    seen: dict[str, dict] = {}
    for a in chosen:
        if a["method"] in seen:
            sys.exit(f"two aggregates report method '{a['method']}' for the same metric: "
                     f"{seen[a['method']]['_path']} and {a['_path']}")
        seen[a["method"]] = a
    return list(seen.values())


def tex_escape(s: str) -> str:
    return (s.replace("\\", "\\textbackslash{}").replace("_", "\\_").replace("%", "\\%")
             .replace("&", "\\&").replace("#", "\\#").replace("$", "\\$"))


# --------------------------------------------------------------------------- teaser (legacy card)
def write_teaser(aggregates: list[dict], out: Path, question: str, finding: str) -> None:
    splits = {s for a in aggregates for s in a["per_split"]}
    traj = {v["n"] for a in aggregates for v in a["per_split"].values()}
    runs = sum(len(a["primary_inputs"]) for a in aggregates)
    contrast = next((a["paired_contrast"] for a in aggregates if a.get("paired_contrast")), None)
    if contrast is None:
        sys.exit("no aggregate carries a paired_contrast; the teaser has no takeaway to show")
    lines = [
        "% GENERATED by scripts/make_paper_data.py. Do not edit by hand.",
        "% source-data: " + ", ".join(sorted(a["label"] for a in aggregates)),
        "% generator:   scripts/make_paper_data.py --teaser",
        "",
        f"\\newcommand{{\\TSsplitseeds}}{{{len(splits)}}}",
        f"\\newcommand{{\\TStrajper}}{{{min(traj) if len(traj) == 1 else f'{min(traj)}--{max(traj)}'}}}",
        f"\\newcommand{{\\TSruns}}{{{runs}}}",
        "",
        f"\\newcommand{{\\TSquestion}}{{{question}}}",
        f"\\newcommand{{\\TSfinding}}{{{finding}}}",
        f"\\newcommand{{\\TSdelta}}{{{contrast['mean']:+.3f}}}",
        f"\\newcommand{{\\TSdeltaunc}}{{{contrast['uncertainty']:.3f}}}",
        f"\\newcommand{{\\TSmetric}}{{{tex_escape(aggregates[0]['metric'].replace('_', ' '))}}}",
        "",
    ]
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {out} from {len(aggregates)} aggregate(s)")


# --------------------------------------------------------------------------- --table-stats
def write_table_stats(aggregates: list[dict], out: Path, precision: int | None) -> None:
    """A per-(method, condition) `mean [lo, hi]` reference, so the table --
    which stays hand-authored; see the module docstring for why -- draws its
    uncertainty from the same computation write_opening() uses for the
    figure's error band, rather than a second, independently-rounded pass
    over the same JSON.

    Comment-only output. Nothing here is \\input; a build that never runs
    this script still compiles, exactly like a table filled before this mode
    existed. Delete it once every number it lists has been transcribed, or
    leave it -- it is inert either way.
    """
    if precision is None:
        allv = [v for a in aggregates for cell in a["per_split"].values() for v in cell["values"]]
        span = (max(allv) - min(allv)) if allv else 1.0
        precision = 3 if span < 1 else (2 if span < 10 else 1)
    lines = [
        "% GENERATED by scripts/make_paper_data.py --table-stats.",
        "% Reference only -- never \\input this file.",
        "%",
        "% Copy the 'mean [lo, hi]' text (not this line) into a table cell, and name",
        "% this file in that table's own 'generator:' comment, exactly as the mean's",
        "% source is named today (references/table-grammar.md, 'Reporting",
        "% uncertainty'). lo/hi = min/max of the repeated-run values behind that",
        "% cell (per_split[condition]['values']) -- the same statistic",
        "% write_opening() already computes for the primary arm's figure error",
        "% band, so a plotted range and a tabled range cannot disagree.",
        "%",
        "% A method's OVERALL row is deliberately absent: 'overall'/'std' is the",
        "% spread ACROSS conditions (heterogeneity), not repeated-run noise, and",
        "% bracketing it here would hand a table a number that looks like a",
        "% confidence interval but is not one. Report Overall as a point estimate.",
        "%",
        f"% precision: {precision} decimal place(s) on every number below.",
        "%",
    ]
    for a in sorted(aggregates, key=lambda a: a["method"]):
        lines.append(f"% {a['method']} ({a.get('display', a['method'])}):")
        for cond, cell in a["per_split"].items():
            vals = cell["values"]
            lines.append(f"%   {cond:<24} {cell['mean']:.{precision}f} "
                         f"[{min(vals):.{precision}f}, {max(vals):.{precision}f}]")
        lines.append("%")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {out} from {len(aggregates)} aggregate(s) at precision {precision} "
          f"-- reference only, never \\input")


# --------------------------------------------------------------------------- legacy --figure
def write_figure(name: str, spec: dict, aggregates: list[dict], out_dir: Path) -> None:
    by_method = {a["method"]: a["per_split"] for a in aggregates}
    series = spec.get("series") or []
    if not series:
        sys.exit(f"figure '{name}' declares no series in the config")
    missing = [s["method"] for s in series if s["method"] not in by_method]
    if missing:
        sys.exit(f"figure '{name}': no aggregate for method(s) {missing}; the figure "
                 "would imply a comparison that was not run")
    band = spec.get("band")
    if band and band["method"] not in by_method:
        sys.exit(f"figure '{name}': band method '{band['method']}' has no aggregate")
    x = spec.get("x", "seed")
    header = [x] + [s["column"] for s in series]
    if band:
        header += [band.get("lo", "lo"), band.get("hi", "hi")]
    keys = condition_keys(by_method)
    rows = [f"# GENERATED by scripts/make_paper_data.py --figure {name}",
            "# Do not edit by hand. Regenerate after any change to the aggregates.",
            " ".join(header)]
    for key in keys:
        cells = []
        for s in series:
            entry = by_method[s["method"]].get(key)
            if entry is None:
                sys.exit(f"figure '{name}': method '{s['method']}' has no key {key}; "
                         "compared methods must have equal coverage")
            cells.append(f"{entry['mean']:.4f}")
        if band:
            values = by_method[band["method"]][key]["values"]
            cells += [f"{min(values):.4f}", f"{max(values):.4f}"]
        rows.append(f"{key} {' '.join(cells)}")
    out = out_dir / spec.get("file", f"{name}.dat")
    out.write_text("\n".join(rows) + "\n", encoding="utf-8")
    print(f"wrote {out} with {len(keys)} row(s)")


def condition_keys(by_method: dict[str, dict], order_from: dict | None = None) -> list[str]:
    """Condition order: numeric keys ascending; otherwise the order they appear
    in `order_from` (the primary arm's aggregate), so figures and tables can
    agree on an order the writer chose rather than an alphabetical one."""
    all_keys = {k for m in by_method.values() for k in m}
    if all(k.lstrip("-").isdigit() for k in all_keys):
        keys = sorted(all_keys, key=int)
    else:
        base = list(order_from.keys()) if order_from else []
        keys = [k for k in base if k in all_keys] + sorted(k for k in all_keys if k not in base)
    for method, splits in by_method.items():
        gap = [k for k in keys if k not in splits]
        if gap:
            sys.exit(f"method '{method}' has no entry for condition(s) {gap}; "
                     "compared methods must have equal coverage")
    return keys


# --------------------------------------------------------------------------- --opening
def write_opening(aggregates: list[dict], out_dir: Path, primary: str, direction: str,
                  delta_mode: str = "absolute") -> None:
    by_method = {a["method"]: a for a in aggregates}
    if primary not in by_method:
        sys.exit(f"--primary '{primary}' is not a method in the aggregates "
                 f"(have: {sorted(by_method)})")
    others = [m for m in by_method if m != primary]
    if not others:
        sys.exit("the opening figure needs at least one comparison arm besides --primary")
    arms = others + [primary]              # primary last so it is drawn on top / rightmost
    keys = condition_keys({m: by_method[m]["per_split"] for m in arms}, by_method[primary]["per_split"])
    if len(keys) < 2:
        sys.exit("the opening figure needs at least two conditions")
    metric = tex_escape(by_method[primary].get("metric_display") or by_method[primary]["metric"].replace("_", " "))
    better = (lambda a, b: a > b) if direction == "up" else (lambda a, b: a < b)

    means = {m: [by_method[m]["per_split"][k]["mean"] for k in keys] for m in arms}
    allv = [v for m in arms for v in means[m]]
    lo_all, hi_all = min(allv), max(allv)
    span = (hi_all - lo_all) or abs(hi_all) or 1.0
    ymin = lo_all - 0.35 * span
    ymax = hi_all + 0.30 * span
    if lo_all >= 0 and ymin < 0:
        ymin = 0.0
    prec = 3 if span < 1 else (2 if span < 10 else 1)
    dprec = 1 if delta_mode == "percent" else prec

    # per-condition delta of the primary over the strongest other arm
    deltas, pairs = [], []
    for i, k in enumerate(keys):
        best_other = None
        for m in others:
            v = means[m][i]
            if best_other is None or better(v, best_other):
                best_other = v
        d = means[primary][i] - best_other if direction == "up" else best_other - means[primary][i]
        if delta_mode == "percent" and best_other:
            d = 100.0 * d / abs(best_other)
        deltas.append(d)
        pairs.append((k, best_other, means[primary][i]))
    pvals = by_method[primary]["per_split"]

    # Two quantities in this project answer to "the margin", and they are not
    # the same statistic. The figure annotates the primary arm's margin over
    # *the strongest other arm in that condition*, which can be a different arm
    # in each condition. `paired_contrast` in the aggregate is against one
    # *named* arm. They coincide only when that arm happens to be strongest
    # everywhere. A writer who reads one and prints the other puts two
    # different numbers for the same-sounding thing in one manuscript, and no
    # gate downstream can tell. So say it here, once, loudly.
    pc = by_method[primary].get("paired_contrast") or {}
    pc_split = pc.get("per_split")
    if isinstance(pc_split, list) and len(pc_split) == len(keys):
        diff = [(k, float(a), b) for k, a, b in zip(keys, pc_split, deltas)
                if abs(float(a) - b) > 0.005 * max(1.0, abs(b))]
        if diff:
            print(f"NOTE: this figure annotates the margin over the strongest other arm in each "
                  f"condition; runs/aggregate__{primary}.json's paired_contrast is against "
                  f"'{pc.get('against', '?')}'. They disagree on "
                  f"{len(diff)} of {len(keys)} conditions, e.g. "
                  + ", ".join(f"{k}: {a:+.3f} vs {b:+.3f}" for k, a, b in diff[:3])
                  + ".\n      Both are defensible; they are different statistics. Say in prose "
                    "which one you are quoting, and never mix them in one manuscript.",
                  file=sys.stderr)

    # ---- opening.dat
    # `toppos` / `topneg` carry the group top only for the sign they name, and
    # `nan` otherwise, so the two delta-label layers below each draw exactly the
    # conditions they are entitled to colour. Doing the sign test here rather
    # than in TeX is what makes it reliable: pgfplots hands the label body a
    # number it cannot always use as a dimension.
    header = (["cond"] + [f"arm{i + 1}" for i in range(len(arms))]
              + ["delta", "lo", "hi", "top", "toppos", "topneg"])
    rows = ["# GENERATED by scripts/make_paper_data.py --opening", " ".join(header)]
    for i, k in enumerate(keys):
        cells = [f"{means[m][i]:.{prec + 1}f}" for m in arms]
        vals = pvals[k]["values"]
        top = max(means[m][i] for m in arms)
        tp = f"{top:.{prec + 1}f}" if deltas[i] >= 0 else "nan"
        tn = "nan" if deltas[i] >= 0 else f"{top:.{prec + 1}f}"
        rows.append(f"{{{tex_escape(str(k))}}} {' '.join(cells)} {deltas[i]:+.{dprec + 1}f} "
                    f"{min(vals):.{prec + 1}f} {max(vals):.{prec + 1}f} {top:.{prec + 1}f} {tp} {tn}")
    (out_dir / "opening.dat").write_text("\n".join(rows) + "\n", encoding="utf-8")

    # ---- opening.tex macros
    n_arms, n_conds = len(arms), len(keys)
    barw = max(2.0, min(9.0, 64.0 / (n_conds * n_arms)))
    barw_small = max(4.0, min(12.0, 40.0 / n_arms))
    panel_w = f"{max(2.2, min(4.2, 13.5 / n_conds)):.2f}cm"
    labels = [tex_escape(by_method[m].get("display", m)) for m in arms]
    maxlen = max(len(str(k)) for k in keys)
    angles = [round(360.0 * i / n_conds, 2) for i in range(n_conds)]
    tex = [
        "% GENERATED by scripts/make_paper_data.py --opening. Do not edit by hand.",
        "% source-data: " + ", ".join(sorted(a["label"] for a in aggregates)),
        "% generator:   scripts/make_paper_data.py --opening",
        f"\\newcommand{{\\OPnarms}}{{{n_arms}}}",
        f"\\newcommand{{\\OPnconds}}{{{n_conds}}}",
        f"\\newcommand{{\\OPmetric}}{{{metric}}}",
        f"\\newcommand{{\\OPdirection}}{{{'\\up' if direction == 'up' else '\\down'}}}",
        f"\\newcommand{{\\OPprimarylabel}}{{{labels[-1]}}}",
        f"\\newcommand{{\\OPprimarycol}}{{arm{n_arms}}}",
        f"\\newcommand{{\\OPymin}}{{{ymin:.{prec + 1}f}}}",
        f"\\newcommand{{\\OPymax}}{{{ymax:.{prec + 1}f}}}",
        f"\\newcommand{{\\OPbarwidth}}{{{barw:.1f}pt}}",
        f"\\newcommand{{\\OPbarwidthsmall}}{{{barw_small:.1f}pt}}",
        f"\\newcommand{{\\OPpanelwidth}}{{{panel_w}}}",
        f"\\newcommand{{\\OPradarangles}}{{{','.join(f'{a:g}' for a in angles)}}}",
        f"\\newcommand{{\\OPradarlabels}}{{{','.join(tex_escape(str(k)) for k in keys)}}}",
        f"\\newcommand{{\\OPdeltamean}}{{{sum(deltas) / len(deltas):+.{dprec}f}}}",
        f"\\newcommand{{\\OPdeltaprec}}{{{dprec}}}",
        f"\\newcommand{{\\OPdeltaunit}}{{{'\\%' if delta_mode == 'percent' else ''}}}",
        # A rotated label's horizontal footprint is what collides with its
        # neighbour, and 45 degrees is the least of it among readable angles:
        # 30 degrees kept "objects365-shift" 24% wider than the space between
        # two condition groups in a radar-halved panel.
        f"\\newcommand{{\\OPxrot}}{{{0 if maxlen <= 6 else 45}}}",
        f"\\newcommand{{\\OPxanchor}}{{{'north' if maxlen <= 6 else 'north east'}}}",
        # \def, not \newcommand: preamble.tex \providecommand's a default so a
        # paper generated before this macro existed still compiles, and a
        # \newcommand here would then clash with it.
        f"\\def\\OPxfont{{{'\\scriptsize' if maxlen <= 10 and n_conds <= 5 else '\\tiny'}}}",
        # A paired scatter labels every point with its condition name. With long
        # names the labels collide with each other and with the points; the
        # honest fallback is an unlabelled scatter whose conditions the caption
        # points at, not a label pile.
        f"\\def\\OPpointstyle{{{'acpointlabels' if maxlen <= 10 else 'acnopointlabels'}}}",
        f"\\newcommand{{\\OPncondsnum}}{{{n_conds}}}",
        "",
    ]
    (out_dir / "opening.tex").write_text("\n".join(tex), encoding="utf-8")

    # ---- opening-series.tex: bars, primary annotated with its delta
    series = ["% GENERATED by scripts/make_paper_data.py --opening"]
    for i, m in enumerate(arms):
        col = f"arm{i + 1}"
        if m == primary:
            series.append(f"\\addplot[fill={PRIMARY_COLOR},draw={PRIMARY_COLOR}!70!black] "
                          f"table[x expr=\\coordindex,y={col}] {{data/opening.dat}};")
        else:
            c = OTHER_COLORS[i % len(OTHER_COLORS)]
            series.append(f"\\addplot[fill={c}!45,draw={c}] "
                          f"table[x expr=\\coordindex,y={col}] {{data/opening.dat}};")
        series.append(f"\\addlegendentry{{{labels[i]}}}")
    # the delta labels: an invisible sharp plot at the top of each group (the
    # tallest bar in that condition), so a label never sits on a taller rival
    # Two label layers, one per sign, each with a fixed colour. A condition the
    # primary arm loses used to be annotated in the good-direction colour, which
    # reads as a win at a glance.
    for col, colour in (("toppos", "ACDelta"), ("topneg", "ACWorse")):
        series.append(f"\\addplot[sharp plot,draw=none,mark=none,forget plot,nodes near coords,"
                      f"point meta=explicit,nodes near coords style={{anchor=south,yshift=1pt,text={colour}}},"
                      f"nodes near coords={{\\pgfmathprintnumber{{\\pgfplotspointmeta}}\\OPdeltaunit}}] "
                      f"table[x expr=\\coordindex,y={col},meta=delta] {{data/opening.dat}};")
    (out_dir / "opening-series.tex").write_text("\n".join(series) + "\n", encoding="utf-8")

    # ---- opening-lines.tex: distribution-lines
    lines = ["% GENERATED by scripts/make_paper_data.py --opening"]
    marks = ["square*", "triangle*", "diamond*", "pentagon*", "o", "x"]
    for i, m in enumerate(arms):
        col = f"arm{i + 1}"
        c = PRIMARY_COLOR if m == primary else OTHER_COLORS[i % len(OTHER_COLORS)]
        mk = "*" if m == primary else marks[i % len(marks)]
        lines.append(f"\\addplot+[{c},mark={mk}] table[x expr=\\coordindex,y={col}] {{data/opening.dat}};")
        lines.append(f"\\addlegendentry{{{labels[i]}}}")
    (out_dir / "opening-lines.tex").write_text("\n".join(lines) + "\n", encoding="utf-8")

    # ---- opening-multiples.tex: one panel per condition, arms as bars at x=0
    mult = ["% GENERATED by scripts/make_paper_data.py --opening",
            f"% group size {n_conds} by 1 -- the block reads \\OPncondsnum"]
    for i, k in enumerate(keys):
        mult.append(f"\\nextgroupplot[title={{{tex_escape(str(k))}}},ybar,bar width=\\OPbarwidthsmall]")
        for j, m in enumerate(arms):
            c = PRIMARY_COLOR if m == primary else OTHER_COLORS[j % len(OTHER_COLORS)]
            mult.append(f"\\addplot[fill={c}!{'100' if m == primary else '45'},draw={c}] "
                        f"coordinates {{(0,{means[m][i]:.{prec + 1}f})}};")
            if i == 0:
                mult.append(f"\\addlegendentry{{{labels[j]}}}")
    (out_dir / "opening-multiples.tex").write_text("\n".join(mult) + "\n", encoding="utf-8")

    # ---- opening-pairs.dat: paired-scatter
    prow = ["# GENERATED by scripts/make_paper_data.py --opening", "cond base primary"]
    for k, b, p in pairs:
        prow.append(f"{{{tex_escape(str(k))}}} {b:.{prec + 1}f} {p:.{prec + 1}f}")
    (out_dir / "opening-pairs.dat").write_text("\n".join(prow) + "\n", encoding="utf-8")

    # ---- radar (five or more conditions)
    if n_conds >= 5:
        rrows = ["# GENERATED by scripts/make_paper_data.py --opening",
                 "angle " + " ".join(f"arm{i + 1}" for i in range(n_arms))]
        for i in list(range(n_conds)) + [0]:            # close the polygon
            rrows.append(f"{angles[i]} " + " ".join(f"{means[m][i]:.{prec + 1}f}" for m in arms))
        (out_dir / "opening-radar.dat").write_text("\n".join(rrows) + "\n", encoding="utf-8")
        rser = ["% GENERATED by scripts/make_paper_data.py --opening"]
        for i, m in enumerate(arms):
            c = PRIMARY_COLOR if m == primary else OTHER_COLORS[i % len(OTHER_COLORS)]
            w = "1.1pt" if m == primary else "0.7pt"
            rser.append(f"\\addplot[{c},line width={w},mark=*,mark size=1.2pt"
                        f"{',fill=' + c + '!12' if m == primary else ''}] "
                        f"table[x=angle,y=arm{i + 1}] {{data/opening-radar.dat}};")
            rser.append(f"\\addlegendentry{{{labels[i]}}}")
        (out_dir / "opening-radar-series.tex").write_text("\n".join(rser) + "\n", encoding="utf-8")

    print(f"wrote {out_dir}/opening.* for {n_arms} arm(s) x {n_conds} condition(s); "
          f"primary '{primary}', mean delta {sum(deltas) / len(deltas):+.{prec}f}"
          + (", radar data written" if n_conds >= 5 else ""))


# --------------------------------------------------------------------------- main
def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("aggregates", nargs="+", type=Path)
    parser.add_argument("--teaser", action="store_true", help="write paper/data/teaser.tex (legacy card)")
    parser.add_argument("--figure", help="name of a figure declared in the config (legacy)")
    parser.add_argument("--table-stats", action="store_true",
                        help="write paper/data/table_stats.tex, a comment-only 'mean [lo, hi]' "
                             "reference for hand-filling the main results table (never \\input)")
    parser.add_argument("--precision", type=int, default=None,
                        help="decimal places for --table-stats (default: inferred from the data's "
                             "span, same heuristic --opening uses)")
    parser.add_argument("--opening", action="store_true",
                        help="write the opening-figure and secondary-figure data of the design family")
    parser.add_argument("--primary", help="method name of this paper's arm (required with --opening)")
    parser.add_argument("--direction", choices=["up", "down"], default=None,
                        help="metric direction; default from paper.json metric_direction, else up")
    parser.add_argument("--metric", help="which metric the figures read when arms report several")
    parser.add_argument("--delta", choices=["absolute", "percent"], default="absolute",
                        help="annotate the primary arm's margin in metric units or as a percentage of the strongest other arm")
    parser.add_argument("--config", type=Path, default=Path("paper.json"),
                        help="project config (default: paper.json)")
    parser.add_argument("--question", default="", help="teaser question, one sentence")
    parser.add_argument("--finding", default="", help="teaser takeaway, one sentence")
    parser.add_argument("--paper-dir", type=Path, default=Path("paper"))
    args = parser.parse_args()

    if not (args.teaser or args.figure or args.opening or args.table_stats):
        parser.error("choose --opening, --teaser, --figure or --table-stats")

    config: dict = {}
    if args.config.exists():
        config = json.loads(args.config.read_text(encoding="utf-8"))
    paper_dir = Path(config.get("paper_dir", args.paper_dir))
    data_dir = paper_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    aggregates = select_metric(load(args.aggregates), args.metric)

    if args.teaser:
        if not args.question or not args.finding:
            sys.exit("--teaser needs --question and --finding")
        write_teaser(aggregates, data_dir / "teaser.tex", args.question, args.finding)
    if args.figure:
        specs = config.get("figures", {})
        if args.figure not in specs:
            sys.exit(f"figure '{args.figure}' is not declared in {args.config}")
        write_figure(args.figure, specs[args.figure], aggregates, data_dir)
    if args.table_stats:
        write_table_stats(aggregates, data_dir / "table_stats.tex", args.precision)
    if args.opening:
        primary = args.primary or (config.get("design", {}).get("evidence", {}) or {}).get("primary")
        if not primary:
            sys.exit("--opening needs --primary <method> (or design.evidence.primary in paper.json)")
        direction = args.direction or config.get("metric_direction") or "up"
        write_opening(aggregates, data_dir, primary, direction, args.delta)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
