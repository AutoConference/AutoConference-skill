# Table grammar

**The shipped scaffolds assume more than one metric.** Every grammar's block
ships with two or more metric columns because five of the seven source papers
report several. A study with one metric and several conditions must remap, not
invent columns: rows stay the compared arms, the columns become the conditions
plus an overall summary, and the grammar's own markers (`\best`, tints, rank
colours, rules) carry over unchanged. Three writers have now arrived at this
mapping independently. Do not fill a metric column with a number the evidence
does not have.

Six main-table grammars exist, one per source paper (`references/design-axes.md`
axis 8): `delta-rows` (P1), `plain-bold` (P2, P5), `family-tint` (P3),
`rank-colors` (P4), `grouped-rules` (P7, caption **below**), `rotated-dense`
(P6, best = underline, worse-than-ours in red). `design_paper.py` installs the
drawn one as `paper/tables/main_results.tex`; the block file documents its
own conventions. The golden rules below apply to all six except where a
grammar's block states otherwise (vertical rules between groups in
`grouped-rules`/`rank-colors`/`delta-rows`; caption position in
`grouped-rules`). Patterns 1–3 below are the `family-tint` instance.

Tables are mandatory. When figures cannot be produced from real data, the tables
carry the paper's evidence alone, so they must be right. Every rule here is
measured from the arXiv:2506.21656 source (`assets/tables/*.tex`).

## Golden rules

1. Caption **above** the table, never below.
2. `booktabs` rules only: `\toprule`, `\midrule`, `\bottomrule`. No `\hline`.
3. No vertical rules. Never a `|` in a column spec.
4. Every value in a column has the same decimal precision. `0.0`, not `0`.
5. One table, one message. Two messages means two tables.
6. Placement `[t!]`. Never `[H]`.
7. Best value **bold**, second best \underline{underlined}, and only when the
   ranking is scientifically meaningful. Never bold and underline the same cell.
8. Metric direction (`$\uparrow$` / `$\downarrow$`) goes in the caption or the
   header, once.
9. Units, sample counts, and the meaning of any missing-value marker go in
   the caption or a table note. Uncertainty is not one of those things left
   to prose: every reported mean carries its interval in the cell beside it.
   See "Reporting uncertainty" below -- this used to say uncertainty could
   live in a caption instead, and that is what let five of six grammars
   ship with no way to carry one.

## Packages

`paper/preamble.tex` already loads these in the order that avoids an xcolor
option clash:

```latex
\usepackage[table,dvipsnames]{xcolor}
\usepackage{colortbl}
\usepackage{booktabs}
\usepackage{nicematrix}   % must come after xcolor
\usepackage{multirow,makecell,threeparttable,siunitx}
```

`nicematrix` must be loaded after `xcolor`; loading it first makes it pull in an
option-free `xcolor` and the build dies with `Option clash for package xcolor`.

## Semantic row tinting

The exemplar tints rows by **family**, never by value. A cell heatmap is
forbidden; color is a redundant grouping cue, not the encoding.

```latex
\definecolor{ACNeutral}{RGB}{230,230,230}   % neutral / reference family
\definecolor{ACCompare}{RGB}{252,228,214}   % comparison family
\definecolor{ACPrimary}{RGB}{207,234,242}   % this paper's family
```

Introduce the key in prose before the table, with inline swatches that match the
row tints exactly:

```latex
\noindent \tightcolorbox{ACCompare}{\textbf{Published baselines.}} ...
\noindent \tightcolorbox{ACPrimary}{\textbf{This study.}} ...
```

and restate it in the caption:

```latex
\colorbox{ACCompare}{\phantom{\rule{1ex}{1ex}}} are published baselines,
\colorbox{ACPrimary}{\phantom{\rule{1ex}{1ex}}} are this study's configurations.
```

Check grayscale and color-vision readability. If the table stops being readable
without color, the grouping must also be carried by row order and a `\midrule`.

## Pattern 1 — full-width main results table

The mandatory table. Grouped families separated by `\midrule`, tinted rows,
`\resizebox` to the text width, 8 pt on 11 pt leading.

```latex
\begin{table}[t!]
  \caption{\textbf{Certified bound ($\downarrow$) under the frozen protocol.}
    \colorbox{ACCompare}{\phantom{\rule{1ex}{1ex}}} are reproduced controls,
    \colorbox{ACPrimary}{\phantom{\rule{1ex}{1ex}}} are the compared selection
    methods. Mean $\pm$ standard deviation over $n$ trajectories per split seed;
    ``--'' marks a configuration that was not executed.}
  \label{tab:main-results}
  \vspace{-0.2cm}
  \centering
  {\fontsize{8pt}{11pt}\selectfont
   \resizebox{\linewidth}{!}{%
     \begin{NiceTabular}{l c c c c c c}[colortbl-like]
       \toprule[1.2pt]
         & \begin{tabular}{c}\textbf{Split}\\\textbf{seeds}\end{tabular}
         & \begin{tabular}{c}\textbf{Traj.}\\\textbf{/split}\end{tabular}
         & \textbf{Mean} & \textbf{Std.} & \textbf{Range}
         & \begin{tabular}{c}\textbf{Paired}\\\textbf{contrast}\end{tabular} \\
       \midrule[1.2pt]\midrule
       \rowcolor{ACCompare} Reproduced control & 5 & 3 & 0.412 & 0.021 & 0.058 & --    \\
       \midrule
       \rowcolor{ACPrimary} \methodmax         & 5 & 3 & 0.398 & 0.019 & 0.051 & \underline{-0.014} \\
       \rowcolor{ACPrimary} \methodrandom      & 5 & 3 & \textbf{0.381} & 0.024 & 0.062 & \textbf{-0.031} \\
       \bottomrule
     \end{NiceTabular}
   }
  }
\end{table}
```

Notes on the grammar:

- `\toprule[1.2pt]` and `\midrule[1.2pt]\midrule` give the heavy double header
  separator the exemplar uses. The closing rule is a plain `\bottomrule`.
- Two-line headers use a nested `\begin{tabular}{c}...\\...\end{tabular}`, which
  keeps columns narrow without rotation.
- `\resizebox{\linewidth}{!}` around the tabular is the exemplar's OWN width
  fix, quoted here because this pattern is measured from its actual source
  file. Every shipped block in this codebase wraps the tabular in `\acfit`
  instead ("Width handling" below) -- a bare `\resizebox` also enlarges a
  table narrower than the measure, which the exemplar's own table never was,
  but ours are not guaranteed to be once `write-up` chooses conditions or an
  interval widens a cell.
- Row tints are applied with `\rowcolor` inside `NiceTabular[colortbl-like]`.

## Pattern 2 — compact secondary table

One or two rows comparing this study against the closest reference. Same
grammar, lighter rules, `\toprule[1pt]` and a single `\midrule`. **No
`\resizebox` here**: a naturally narrow table stretched to the text width
renders at a comically large type size. Reserve `\resizebox` for tables that
are genuinely too wide.

```latex
\begin{table}[t!]
  \caption{\textbf{Per-split paired contrasts.} Positive values favor
    \methodrandom. Pairing is exact: same split seed, same trajectory index,
    same evaluation semantics.}
  \label{tab:paired}
  \vspace{-0.2cm}
  \centering
  {\fontsize{8pt}{11pt}\selectfont
     \begin{NiceTabular}{l c c c c c}[colortbl-like]
       \toprule[1pt]
       \textbf{Split seed} & \textbf{1} & \textbf{2} & \textbf{3} & \textbf{4} & \textbf{42} \\
       \midrule
       \methodmax    & 0.401 & 0.395 & 0.412 & 0.388 & 0.394 \\
       \rowcolor{ACPrimary} \methodrandom & 0.379 & 0.384 & 0.398 & 0.371 & 0.373 \\
       \midrule
       Difference    & 0.022 & 0.011 & 0.014 & 0.017 & 0.021 \\
       \bottomrule
     \end{NiceTabular}
  }
\end{table}
```

## Pattern 3 — paired ablation tables

Two numbered tables side by side in one float, at `0.48` and `0.44` of the text
width. Both captions centered, both with their own `\label`, identical numeric
precision on both sides.

```latex
\begin{table}[t!]
  \centering
  \begin{minipage}{0.48\textwidth}
      \centering
      \captionsetup{justification=centering, singlelinecheck=false}
      \caption{\textbf{Effect of trajectory count.}}
      \vspace{-0.1cm}
      \label{tab:trajectory-count}
      {\fontsize{8pt}{11pt}\selectfont
       \begin{NiceTabular}{l cccc}[colortbl-like]
         \toprule[1.2pt]
         \textbf{Metric} & \textbf{1} & \textbf{2} & \textbf{3} & \textbf{5} \\
         \midrule[1.2pt]
         Mean bound & 0.394 & 0.388 & \textbf{0.381} & 0.382 \\
         Std. bound & 0.000 & 0.017 & 0.024 & 0.023 \\
         \bottomrule[1.2pt]
       \end{NiceTabular}%
      }
  \end{minipage}
  \hfill
  \begin{minipage}{0.44\textwidth}
       \centering
       \captionsetup{justification=centering, singlelinecheck=false}
       \caption{\textbf{Effect of experiment scale.}}
       \vspace{-0.1cm}
      \label{tab:scale}
      {\fontsize{8pt}{11pt}\selectfont
       \begin{NiceTabular}{l ccc}[colortbl-like]
         \toprule[1.2pt]
         \textbf{Setting} & \textbf{Epochs} & \textbf{Comp.} & \textbf{Bound} \\
         \midrule[1.2pt]
         Reduced  &  12 &   120 & 0.381 \\
         Original & 200 & 20000 & 0.352 \\
         \bottomrule[1.2pt]
       \end{NiceTabular}%
      }
  \end{minipage}
\end{table}
```

## Reporting uncertainty

**Every value a grammar reports needs its interval beside it**, not just a
mean. Rule 9 used to let uncertainty live in the caption instead of the
cell; that is exactly what let five of the six shipped grammars ship with
no way to carry one at all, even though the number was already sitting in
the aggregate next to the mean (`per_split[condition]['values']`, right
beside `per_split[condition]['mean']`). Read this before filling in any
grammar's `\slot{lo, hi}`.

**Form: `mean [lo, hi]`, never `mean $\pm$ half-width`.** Two independent
reasons point the same way:

- *The data.* `lo`/`hi` is an observed minimum and maximum across repeated
  runs (or, for a proportion, a Wilson score interval) -- read off the
  evidence, not produced by a symmetric formula, and usually not symmetric
  around the mean. One real cell: `50.9 [50.4, 51.3]` is $-0.5/+0.4$.
  Collapsing that to a half-width and writing `50.9 $\pm$ 0.45` states a
  precision the evidence does not have.
- *The platform.* `\pm` only draws anything inside math mode (`$\pm$`), and
  the submission pipeline preserves inline math as raw LaTeX source in
  `body_md` -- what a reviewing agent actually reads. The shape gate's
  interval check (`agent-skills/submission/scripts/check_submission_shape.py`,
  `CI_NOTATION`) matches a literal `±` glyph, `+/-`, or `[lo, hi]`; it does
  not match `\pm`. Running a real table cell through the submission
  converter confirms it: `$\pm$` survives into `body_md` as the four
  characters `$\pm$`, and the checker does not count it -- a table using it
  compiles into a correct-looking PDF while remaining invisible to the
  exact check this convention exists to satisfy. A bare Unicode `±` (no
  `$`) does not rescue it either: test-compiled through this project's own
  preamble, it prints a garbled substitute glyph, not a plus-minus sign.
  `[lo, hi]` is plain text. It survives LaTeX, survives the markdown
  conversion byte-for-byte, and is what the checker is actually looking
  for. Use it, in every grammar, without exception.

  (`family-tint`'s own source exemplar (Pattern 1 above) reports "Mean
  $\pm$ standard deviation" in prose, with Mean and Std. as separate table
  *columns* -- a different, genuinely symmetric statistic from the `lo,
  hi` this codebase's aggregates carry. Describing an estimator in a
  caption is not a per-value interval and is not what `CI_NOTATION` counts.
  Do not read that prose as license to write `$\pm$` inside a data cell.)

**Where the numbers come from.** `lo`/`hi` = `min`/`max` of
`per_split[condition]['values']` in the arm's own `runs/aggregate__*.json`
-- the same raw list `scripts/make_paper_data.py`'s `write_opening()`
already reduces to a `lo`/`hi` pair for the primary arm's figure error band
(`paper/data/opening.dat`). A table cell and a plotted error bar drawing
from the same two numbers is what keeps them from disagreeing; do not
derive a table's interval a different way (a fresh std, a recomputed CI)
than whatever figure sits next to it. Run
`make_paper_data.py --table-stats runs/aggregate__*.json --precision N` to
get every `mean [lo, hi]` pre-computed and precision-matched
(`paper/data/table_stats.tex` -- comment-only, never `\input`; cite it in
the table's own `generator:` comment). This does not make table-filling
automatic -- a table's layout stays too bespoke per grammar for a script to
lay out, same as before -- it just removes the mental arithmetic of
rounding `lo`/`hi` to match the mean by hand.

**What never gets bracketed.** A grammar's Overall/Average/Mean summary
column, where one exists, stays a point estimate. That column's own `std`,
when the aggregate reports one, is the spread ACROSS conditions
(heterogeneity, e.g. how different HAR is from ECG) -- not repeated-run
noise on any single number -- so bracketing it would print something
shaped exactly like a confidence interval that is not one: the same
fabricated-spread failure `quality.example.json` names for instance counts
("Reporting 'three seeds' while holding instances fixed... would be a
fabricated spread"). Leave it a point value and let the per-condition
cells around it carry the real intervals. `delta-rows`'s $\Delta$ row is
exempt for a related reason: it is already a difference or ratio of two
uncertain quantities, and propagating an interval through that arithmetic
is a new statistical claim this codebase does not make -- consistent with
`check_paper_structure.py` already exempting delta/contrast columns from
its numeric checks (`NONMETRIC_COLUMN_KEYWORDS`).

**Precision, always.** Same decimal count on the mean AND both interval
bounds, in every cell of the column -- rule 4 already required this for the
mean; it applies just as strictly to `lo` and `hi`. `is_numeric_cell()` in
`check_paper_structure.py` recognises `[` and `]` alongside a literal `±`,
so a bracketed cell's three numbers are pooled into the same per-column
precision check as everything else, and the cell's point estimate still
counts toward `evidence_numbers()` traceability for the abstract/conclusion
check. Keep that recognition if you ever touch `is_numeric_cell()` again:
losing it silently reclassifies a headline result in the abstract as
"unsupported" the moment its table cell grows an interval, which is a
self-inflicted gate failure, not a real one.

**How much of the table gets it.** Give every row's every per-condition
cell the full treatment first; do not default to bracketing only the
primary row to save width. It fits: the four grammars actually proven on
real papers (`delta-rows`/S03, `plain-bold`/S16+P247, `grouped-rules`/
S10+S21, `rotated-dense`/S26) all render the complete per-cell treatment at
their default font size with zero overfull boxes, including the two-level
grouped-and-ruled header case and the 7pt eight-column rotated-header case
-- a two-level header or rotated headers reclaim more vertical room than an
interval costs horizontally, and `\acwidetable` gives more width margin
than a single-column table's plain `\linewidth` would. Treat that as
validated headroom on the draws checked so far, not a blanket guarantee for
every future one: build and look at the rendered page (the pre-submission
checklist below) before trusting it on a table with more columns or a
narrower layout than any of those six, and drop a column or shorten a
header before shrinking the whole table if it does not fit -- `\acfit`
refuses to enlarge a table, it does not refuse to shrink one past legible.

## Number and precision rules

| Situation | Rule |
|---|---|
| Metrics | Same decimal count in every cell of the column |
| Uncertainty | `0.381 [0.357, 0.405]` -- brackets, not `$\pm$` (see "Reporting uncertainty" above for why); same precision on the mean and both bounds |
| Percentages | `\%` escaped, aligned, same precision |
| Large integers | Consistent grouping across the whole table |
| Zero | `0.000` when the column has three decimals |
| Not executed | A single marker, defined in the caption |

`check_paper_structure.py` reads every numeric column and fails the gate when a
column mixes precisions.

## Table notes

For provenance or estimator detail that does not fit the caption:

```latex
\begin{threeparttable}
  ... tabular ...
  \begin{tablenotes}[flushleft]\footnotesize
    \item Aggregates are computed from preserved primary runs; the aggregation
      manifest enumerates every raw input path.
  \end{tablenotes}
\end{threeparttable}
```

**Known trap:** a `threeparttable` wrapping a `resizebox`'d `NiceTabular`, with
`\caption` and `\label` placed inside the `threeparttable` (the idiomatic
placement, so the notes align with the table width), has silently dropped the
`\label` in practice — it never reached `main.aux`, and every `\cref` to that
table rendered a literal `??`, with no error and no warning naming the real
cause (only the generic "Reference ... undefined"). `check_paper_structure.py`
now cross-checks every `\ref`/`\cref` against the compiled `main.aux` to catch
exactly this, but the safer fix is to not need a tablenotes list at all: fold
the note into the caption (table-grammar's own main-results pattern does this)
unless the note genuinely cannot fit there.

## Width handling, in priority order

1. `\acfit{...}` around the tabular -- **never a bare `\resizebox`**. Unlike
   `\resizebox{\linewidth}{!}{...}`, `\acfit` is shrink-only
   (`\ifdim\width>\acfloatwidth\acfloatwidth\else\width\fi`): a plain
   `resizebox` ENLARGES a table narrower than the measure to fill it, which
   is what once made a table print at 1.28x body text size, and it has been
   fixed once already. Adding an interval to every cell is exactly the kind
   of change that can flip a table from narrower-than-measure to
   wider-than-measure, so this is not a one-time migration; check it again
   whenever a table's content grows.
2. `{\fontsize{8pt}{11pt}\selectfont ...}` around the float body.
3. Abbreviate headers and expand them in the caption.
4. Two-line headers with a nested `tabular`.
5. `\setlength{\tabcolsep}{4pt}`.
6. Drop a column, or the least load-bearing metric, before shrinking the
   whole table further. This is the fallback once 1–5 are exhausted, not a
   substitute for them -- see "Reporting uncertainty" above for why this
   applies specifically to a table whose cells just grew an interval.

Never squeeze columns into an overfull `\hbox`. An overfull box in a table is a
build failure, not a warning to ignore.

## Evidence rules

- A table cell is filled only from a traceable aggregate. Never from prose,
  memory, a narrative Markdown file, or an agent log. `lo`/`hi` are held to
  the same rule as the mean: both come from the arm's own
  `per_split[condition]['values']`, optionally by way of
  `paper/data/table_stats.tex` (`make_paper_data.py --table-stats`, itself
  reading nothing but that same aggregate). Never estimate an interval from
  the metric's typical spread, a rule of thumb, or a number in a different
  condition's row.
- A row aggregating a single run reports `n=1` explicitly and cannot be bolded
  as a headline result, and cannot carry a bracketed interval either -- a
  single run has no min/max to report.
- A value whose provenance is `unverifiable` never appears in a main-body table.
  Move it to the appendix with its status, or drop it.
- Bold marks the paper's own supported best. Bolding an unsupported win is the
  single most damaging table defect available.

`check_paper_structure.py` mechanically checks this for the column-wise
pattern used above (rows are the compared entities, one metric per column,
direction read from the caption's `\up`/`\down`): a bolded cell must equal the
column's best value and an underlined cell the column's second-best, or the
gate errors. It deliberately skips a column whose header names a count, a
size, a spread statistic, or a contrast (never a rival measurement), and skips
a derived summary row (a "Difference" row) the same way. It also deliberately
skips the *transposed* ablation-table pattern — statistics as rows, the swept
setting as columns — detected from a row label that itself names a statistic
(`Mean`, `Std.`, …): comparing a mean against a standard deviation as if they
were rival methods would be a worse defect than the one being checked for, so
that pattern is left unchecked rather than guessed at. A table in that pattern
gets no mechanical help here; earn the bold by hand.

## Pre-submission checklist

- [ ] Caption above, and it states what, where, and the takeaway.
- [ ] `booktabs` rules only; no `\hline`, no `|`.
- [ ] Consistent decimal precision per column, mean AND interval bounds alike.
- [ ] Metric direction stated once.
- [ ] Bold/underline convention applied consistently and earned by evidence.
- [ ] Family tints match the swatches introduced in prose.
- [ ] Readable in grayscale.
- [ ] Every per-condition mean carries `[lo, hi]`, never `$\pm$`, sourced from
      that arm's own `per_split[condition]['values']` ("Reporting
      uncertainty" above). Overall/Average and any Delta/contrast row stay
      point estimates.
- [ ] `\acfit`, never a bare `\resizebox` -- check again if the table's
      content changed since the last time you checked.
- [ ] No overfull or underfull box from any table row.
- [ ] Every `\label` referenced from prose.
- [ ] No `\slot` remains.
- [ ] Opened the rendered page at readable size and looked at the table --
      no gate reads the drawn shapes, and a column can overflow visually
      without tripping an overfull-box warning.
