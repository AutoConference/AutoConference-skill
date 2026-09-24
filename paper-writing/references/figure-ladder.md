# Figure ladder

Figures are the part of the exemplar's layout that is hardest to reproduce
without an illustrator. This file decides what to produce instead, so that a
missing figure never becomes a fake figure and never becomes a hole in the page.

The governing rule: **tables and equations are mandatory, figures degrade.**
Choose the highest tier the available evidence and tooling actually support, and
never mix a lower tier's output into a higher tier's claim.

## The tiers

### Tier A — designed artwork

Vector PDF or SVG produced by a real design pass: the exemplar's teaser,
architecture panel, and qualitative comparison figures are Tier A.

Requires: an illustration toolchain and content worth illustrating. Raster
imagery must be at least 300 ppi at final size.

Use Tier A only when the artwork is genuinely produced. Do not attempt Tier A
and settle for a box diagram labeled as an architecture.

### Tier B — data plots from source data

`pgfplots` reading a `.dat` or `.csv` file written by the analysis script. This
is the default for any quantitative visual and it needs no external tools: the
figure is generated at compile time from real numbers.

```latex
\begin{figure}[!t]
  \centering
  \begin{tikzpicture}
    \begin{axis}[
      width=0.92\linewidth, height=5.2cm,
      xlabel={split seed}, ylabel={certified bound $\downarrow$},
      xtick=data, symbolic x coords={1,2,3,4,42},
      ymajorgrids, grid style={ACMuted!25},
      legend style={font=\scriptsize, at={(0.5,1.04)}, anchor=south, legend columns=-1},
      tick label style={font=\scriptsize}, label style={font=\small},
    ]
      \addplot+[ACCompare!60!black, mark=square*] table[x=seed,y=maxerr] {data/bounds.dat};
      \addplot+[ACBlue, mark=*]                    table[x=seed,y=random] {data/bounds.dat};
      \legend{\methodmax, \methodrandom}
    \end{axis}
  \end{tikzpicture}
  \caption{\textbf{Per-split distribution of the certified bound.} Each point is
    the mean over three trajectory seeds at a fixed split; error bars are the
    trajectory range. The method ordering is not stable across splits.}
  \label{fig:distribution}
\end{figure}
```

The `.dat` file is written by the same script that writes the aggregation JSON.
The figure's manifest names that script and its raw inputs. A plot is never
drawn from values retyped out of prose or out of a table.

### Tier C — structural TikZ, no external assets

A box-and-arrow diagram, a factor matrix, or a labeled schedule, drawn in TikZ
with the preamble's `acbox` / `acsoft` / `acarrow` styles. This is the floor:
it always compiles, needs no data, and needs no images.

**Tier C is not the same as austere.** A reader who compared our system figure
with the seven source papers said it looked too plain and that the icons were
missing, and they were right: all seven put a glyph in every box, key their
frozen and trained stages with a snowflake and a flame, tint the region the
paper contributed, and carry a legend. None of that is evidence, so none of it
changes the tier — an icon is a label. `references/figure-icons.md` is the
vocabulary and the rules for using it.

The one Tier C device that needs care is `\acgrid`, a checkered square standing
for an attention or score matrix. It says *a matrix happens here* and nothing
about its values. A caption that invites it to be read as a heat map of real
numbers turns a legitimate diagram into a fabricated figure.

Tier C is legitimate for:

- the method overview figure — what is fixed, what varies, what is reported;
- the worked instance beside the results panel in a `composite` opening;
- a protocol or pipeline schematic.

Tier C is **not** legitimate for anything quantitative. A TikZ drawing that
implies a distribution, a ranking, or a magnitude without reading real data is
a fabricated figure regardless of how it is labeled.

### Tier D — omit

When neither real artwork nor real data exists, **delete the float and reflow
the prose**. Absorb its content into a table row, an equation, or a sentence.

Never ship, in any build that anyone else will read:

- a box containing `DATA SLOT`, `TBD`, `Figure omitted`, or `Coming soon`;
- a chart with invented bar heights, invented axis ranges, or a radar polygon
  drawn to look plausible;
- a placeholder image, a stock diagram, or a screenshot standing in for a plot.
- an image-model rendering of a system figure. It is raster where the paper is
  vector, its small labels are unreliable, and it cannot be reproduced from a
  seed the way every other axis in this family can.

A paper with three real tables, five narrated equations, and two Tier C diagrams
is a complete paper. A paper with eight fake figures is not a paper.

## Decision rule

```
Is the visual quantitative?
├── yes → Is there a traceable aggregate or raw series to plot?
│         ├── yes → Tier B
│         └── no  → Tier D. Put the numbers in a table instead.
└── no  → Does designed artwork already exist for it?
          ├── yes → Tier A
          └── no  → Tier C
```

## The opening figure

What page 1 carries is an axis of the design (`design-axes.md` axis 2),
decided from the evidence and the layout, never assumed:

| value | source | what it is |
|---|---|---|
| `none` | P5, P6 | nothing; the overview figure appears by page 4 |
| `results` | P1 | numbered, captioned quantitative panel: grouped bars per condition, the primary arm's delta over the strongest other arm annotated above its bar; a radar when there are ≥ 5 conditions. Column-width in `cvpr2` |
| `results-wide` | P2, P4, P7 (position) | the same panel full width above the abstract |
| `composite` | P3 | unnumbered, uncaptioned: a Tier-C worked instance (one input → the method → its output, in words, no magnitude) beside the results panel; `neurips1` only |

Every number in any of these is read at compile time from
`paper/data/opening.dat`, written by `make_paper_data.py --opening`. The
panel is Tier B; the worked instance in `composite` is Tier C and must never
imply a magnitude or an image that does not exist.

Plan the panel before drawing it, the way a multi-panel figure is planned:
write the one sentence the figure must establish, then give each panel a
distinct evidence role (setup / decisive comparison / decomposition /
boundary). Two panels with the same role are one panel.

The former Question / Design / Finding card (`figures/hero.tex`) matches no
real paper and is kept only as the fallback when the aggregates cannot
support a plot at all.

## Caption discipline, all tiers

- Caption below the figure, above the table.
- Open with a bold lead phrase, then what is shown, what is compared, what to
  notice.
- Name the estimator and the sample count for anything aggregated.
- Say what a missing value or a dashed element means.
- Do not repeat the axis labels in prose form; add the interpretation instead.

## Manifest requirement

Every quantitative figure gets a two-line manifest committed next to it:

```
% source-data: runs/aggregate__<label>.json -> paper/data/bounds.dat
% generator:   scripts/make_paper_data.py --figure distribution
```

`check_paper_structure.py` warns when a figure environment containing an `axis`
or `\includegraphics` has no manifest comment.
