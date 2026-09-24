# Design axes: the family contract

The layout contract used to be measured from one paper (arXiv:2506.21656) and
every one of its choices became a rule. Seven template papers were then read
completely (`../../writing-redesign/notes/`), and of the contract's fifteen
structural rules only three held across all seven. The other twelve were one
paper's taste.

This file replaces those twelve rules with **axes**: for each design decision,
the values that real papers were observed to take, which paper took them, and
what each value means for the manuscript. A paper's design is a **drawn,
recorded combination** of one value per axis, written to `paper.json` under
`design` by `scripts/design_paper.py` and read by every gate. Two papers with
different draws are different papers; the same seed reproduces the same draw.

Nothing here is invented. Every value below appears in at least one of:

| id | paper | format |
|---|---|---|
| P1 | Visual-RFT, arXiv:2503.01785 | CVPR two-column |
| P2 | PlayerOne, arXiv:2506.09995 | NeurIPS single-column preprint |
| P3 | Fine-Grained Preference Optimization, arXiv:2506.21656 | NeurIPS 2025 |
| P4 | ChordEdit, arXiv:2602.19083 | CVPR two-column |
| P5 | ThinkJEPA, arXiv:2603.22281 | NeurIPS single-column preprint |
| P6 | VL-JEPA, ICLR 2026 | ICLR single-column |
| P7 | EgoX, CVPR 2026 | CVPR two-column |

## Invariants (still hard rules, in every design)

- Section spine Abstract → Introduction → Method → Experiments → Conclusion.
  Related Work sits between Introduction and Method, or in the appendix with a
  one-paragraph stub in the main body.
- An overview figure appears before the method's first display equation.
- Every caption opens with a bold lead phrase.
- Bold inline paragraph leads appear in Method and Experiments.
- Tables use rules, never boxes; some marking of the best value exists.
- Slot discipline, the evidence interface, citation verification, the render
  gate, the synthetic-evidence disclosure, and the figure ladder are unchanged.

## The axes

Each axis lists its values as `value` — papers — what it means. The block
file that implements a value is named where one exists; values with no file
are prose organization the writer follows and the gate checks.

### 1. `layout` — page family

| value | papers | what it means |
|---|---|---|
| `neurips1` | P2 P3 P5 | single column, thick rule above the title, bold headings, numeric `[n]` citations, `plainnat` |
| `iclr1` | P6 | single column, small-caps headings, running header, author–year citations (`\citep`/`\citet`), `iclr2026_conference.bst` |
| `cvpr2` | P1 P4 P7 | two columns, plain title block, italic abstract, numeric citations, `ieeenat_fullname.bst`; full-width floats are `figure*`/`table*` |

Files: `template/layouts/<layout>/main.tex`, `preamble-layout.tex`, the
official style file. Chosen by the operator (`--layout`) or drawn (`--layout
draw`).

### 2. `opening` — what is on page 1 besides the title and abstract

| value | papers | what it means |
|---|---|---|
| `none` | P5 P6 | nothing; the abstract and §1 start on page 1; the overview figure must appear by page 4 |
| `results` | P1 | a **numbered, captioned quantitative panel** drawn from the aggregates: grouped bars per condition with the primary arm's delta over the strongest baseline annotated above each bar; a radar panel is added when there are ≥ 5 conditions. Column-width in `cvpr2` (floats to the top of a column, P1), full-width in single-column layouts |
| `results-wide` | P2 P7 (position) | the same panel placed **full width above the abstract**, the way P2/P4/P7 place their showcase. In `cvpr2` this is the `\twocolumn[...]` slot |
| `composite` | P3 | **unnumbered, uncaptioned** full-width composite: a Tier-C worked instance of the task (input → method → output for one case, no magnitudes) beside the results panel. `neurips1` only |
| `design-card` | none | the former Question / Design / Finding card. Retained only as the fallback when the aggregates cannot support a plot at all. Never drawn |

`showcase` (P2 P4 P7's image galleries) is what those papers actually show; it
needs Tier A imagery and is unreachable for a synthetic study. The draw never
produces it; if Tier A imagery exists, the operator can pass
`--prefer opening=showcase` and supply `figures/opening.tex` by hand.

Files: `template/blocks/opening/<value>.tex` → `paper/figures/opening.tex`;
data from `make_paper_data.py --opening`.

### 3. `contributions` — how the introduction's contribution list is set

| value | papers |
|---|---|
| `bullets` | P2 P5 P6 P7 — `\item` bullets, one sentence each, bold key phrase optional |
| `numbered` | P3 — `\item[\textbf{(1)}]` inside an itemize |
| `inline` | P1 — a single paragraph with bold `(1)`, `(2)`, `(3)` run in |
| `none` | P4 — "Our key contribution is …" stated inline, no list |

Files: `template/blocks/contributions/<value>.tex` → `paper/blocks/contributions.tex`,
which defines `\begin{contributionlist}` and `\contribution{...}` for the
introduction to use.

### 4. `related` — where and how Related Work is organized

| value | papers |
|---|---|
| `themes-2` | P1 P2 — two bold inline themes, one dense paragraph each, each ending by positioning this paper |
| `themes-3` | P3 P5 — three bold themes, same shape, then a closing "scope" paragraph |
| `subsections` | P7 — numbered `\subsection`s, one per line of work |
| `appendix` | P4 P6 — one paragraph in the main body naming the families and pointing to the appendix; the full section is the first appendix section |

Files: `template/blocks/related/<value>.tex` → `paper/sections/02_related_work.tex`;
for `appendix` the full section is appended to the appendix scaffold.

### 5. `method_open` — how the Method section begins, after the overview figure

| value | papers |
|---|---|
| `roadmap` | P2 — "Sec. 3.1 introduces … Sec. 3.2 … Sec. 3.3 …" then subsections |
| `formal` | P5 P7 — "Given X … the goal is to produce Y" stated inline with notation |
| `components` | P6 — a numbered list of the method's components with monospace names, each one sentence |
| `preliminaries` | P1 P4 — a first subsection restating the prior framework the method builds on |

Files: `template/blocks/method-open/<value>.tex` → `paper/blocks/method_open.tex`,
`\input` at the top of `03_method.tex`.

### 6. `equations` — how much display math the method carries

| value | papers | numbered displays in Method | gate floor |
|---|---|---|---|
| `none` | P6 | 0; the method is prose and inline math | 0 |
| `sparse` | P2 | ~4 | 2 |
| `moderate` | P5 P7 | 5–8 | 5 |
| `dense` | P1 P3 | 9–12 | 9 |
| `sectioned` | P4 | section-prefixed numbers `(3.1)`, key results boxed, an `algorithm` float | 5 |

`sectioned` adds `\numberwithin{equation}{section}` and the `algorithm`
packages in `design.tex` and requires one `\begin{algorithm}` in the method.

### 7. `experiments` — how the Experiments section is organized

| value | papers | subsection sequence the skeleton provides |
|---|---|---|
| `by-task` | P1 | Setup; then one subsection per task, each with its own table; **no ablation section** |
| `setup-main-qual-ablation` | P3 | Setup → Main results → Qualitative/distributional → Ablations |
| `setup-ablation-sota` | P2 | Setup → Ablation study → Comparison with state of the art |
| `qual-quant-ablation` | P7 | a bullet list of research questions, then Setup → Qualitative → Quantitative → Ablation |
| `bold-lead-stream` | P5 | Setup; then one long Results subsection of bold-lead paragraphs, some ending in a colon |
| `roadmap-setup-results` | P6 | a roadmap paragraph, then 4–7 subsections each with "Evaluation Setup." / "Results." leads |
| `separate-ablation-section` | P4 | Experiments (Setup, Comparison) and a **top-level Ablation Study section** with 3–4 subsections |

Files: `template/blocks/experiments/<value>.tex` → `paper/sections/04_experiments.tex`
(and `04b_ablation.tex` for `separate-ablation-section`).

### 8. `main_table` — the grammar of the main results table

Rows are arms (baseline family, then this paper's family); columns are
conditions and an overall column. What differs is how the table is drawn.

| value | papers | marking of best | caption | notes |
|---|---|---|---|---|
| `delta-rows` | P1 | a bold green `Δ` row with explicit `+` signs under each family pair | above | one vertical rule after the overall column; no bold cells |
| `plain-bold` | P2 P5 | `\best` = bold on the winning cell | above | plain booktabs, no tints |
| `family-tint` | P3 | `\best` bold, `\second` underline; rows tinted by family | above | the former default |
| `rank-colors` | P4 | `\rankone` `\ranktwo` `\rankthree` = yellow / orange / blue cell backgrounds; ✓ / ✗ property columns | above | `Type` multirow groups |
| `grouped-rules` | P7 | `\best` bold, `\second` underline; per-column `\up`/`\down`; two-level header with vertical rules **between groups only** | **below** | `Scenario` multirow groups |
| `rotated-dense` | P6 | `\best` = **underline**; scores worse than ours in `\worse{}` red | above | rotated column headers, 7 pt |

The caption position is a property of the grammar, not a separate axis:
only `grouped-rules` places it below. The gate reads the expected position
from the grammar.

Files: `template/blocks/tables/<value>.tex` → `paper/tables/main_results.tex`.
The semantic markers `\best`, `\second`, `\rankone`…, `\deltarow`, `\worse`
are defined in `paper/design.tex`, so the gate checks the marker, not the
rendering.

### 9. `ablation` — the grammar of the ablation table(s)

| value | papers |
|---|---|
| `none` | P1 — bound to `experiments = by-task` |
| `cumulative` | P2 — rows `Baseline` / `+ A` / `+ A&B` / … / `Ours` (bold); one build-up |
| `paired-minipage` | P3 — two small tables side by side, metrics as rows, swept setting as columns |
| `wo-rows` | P5 P7 — `Full` first, then `w/o A`, `w/o B`, …, same metric columns as the main table |
| `default-delta` | P6 — the default setting's row tinted; every other cell carries a small signed `(±δ)` in green/red |
| `naive-vs-ours` | P4 — two-level header `Naive` \| `Ours` over the same metrics |

Files: `template/blocks/ablation/<value>.tex` → `paper/tables/ablations.tex`.

`cumulative` assumes the evidence contains a build-up: runs with one component
added at a time. An evidence package of whole arms only does not have that. The
honest fallback, which the first writer to hit this arrived at, is to use the
compared arms themselves as the build-up and say in the caption that the rows
are not the same method with a component switched off, then state the gap in
Limitations. Never invent a per-component row.

### 10. `qualitative` — the secondary evidence figure

For a synthetic study every option is Tier B from the same aggregates.

| value | papers (grammar) |
|---|---|
| `none` | P5 P6 |
| `distribution-lines` | P3 — per-condition means as lines, one per arm, with the primary arm's spread band |
| `small-multiples` | P1 (bars), P4 (2×2 panels) — one small panel per condition, arms as bars |
| `paired-scatter` | P4 (efficiency frontier) — per-condition points, primary vs. strongest baseline, with the diagonal |

Files: `template/blocks/qualitative/<value>.tex` → `paper/figures/results_panel.tex`.

### 11. `appendix` — what follows the references

| value | papers |
|---|---|
| `none` | P1 P2 |
| `lettered` | P3 — lettered sections A–H in the PDF, ≥ 1500 words |
| `deep` | P5 — lettered sections, each further study as `X.1 Experimental setting. / X.2 Experimental details. / X.3 Analysis.` |
| `supp-toc` | P4 — a supplementary title page with a table of contents, then lettered sections including theorem-style derivations and a symbols table |
| `single` | P6 — one appendix section only |

Files: `template/blocks/appendix/<value>.tex` → `paper/sections/06_appendix.tex`.

### 12. `limitations` — where limitations are stated

| value | papers |
|---|---|
| `appendix` | P3 P5 — a lettered appendix section |
| `conclusion-paragraph` | P2 P7 — a bold-lead `Limitations.` paragraph closing the conclusion |
| `own-section` | P6 — an unnumbered `Limitations` section after the conclusion |
| `absent` | P1 — not stated |

### 13. `devices` — zero to two distinctive devices

| value | papers | what it is |
|---|---|---|
| `principle` | P3 | `\textbf{Principle N}: \textit{one-sentence rule.}` + evidence paragraph, at most twice |
| `research-questions` | P7 | a bullet list of "How …?" questions opening Experiments, each pointing at its subsection |
| `rhetorical-hook` | P7 | the introduction opens with a question addressed to the reader |
| `llm-usage` | P6 | an unnumbered `LLM Usage` section after the conclusion |
| `symbols-table` | P4 | a symbols table in the appendix |
| `prior-limitations` | P5 | the introduction names numbered bold limitations of prior work before proposing |
| `data-card` | P2 | a tiny dataset-statistics table with ✓ / × cells in the setup |
| `efficiency-scatter` | P4 | quality-vs-cost scatter as the second figure |

Files: `template/blocks/devices/<value>.tex` where a snippet exists.

### 14. `palette` — the visual key

Colour was the one thing every paper in the family shared: one blue scheme, so
five papers side by side read as one template. Each value is a **published**
qualitative scheme, chosen for print and for colour-vision deficiency, and each
redefines the same semantic tokens — so a block never names a colour, and a
paper changes its whole visual key in one file.

| value | source | primary hue |
|---|---|---|
| `ac-house` | the exemplar's own scheme (arXiv:2506.21656) | navy |
| `okabe-ito` | Okabe & Ito, popularised by Wong, *Points of View: Color blindness*, Nature Methods 8:441 (2011) | azure |
| `tol-bright` | Paul Tol's `bright` qualitative scheme (SRON) | magenta |
| `tol-muted` | Paul Tol's `muted` qualitative scheme (SRON) | indigo |
| `brewer-dark2` | ColorBrewer qualitative `Dark2` (Brewer et al.) | green |
| `warm-ochre` | ColorBrewer PuOr / RdYlBu warm end | burnt orange |

Tokens every palette defines: `ACBlue` (this paper's arm, the title rule, links),
`ACCyan` (secondary), `ACPrimary` / `ACCompare` / `ACNeutral` (the three family row
tints), `ACGreen` = `ACDelta` (a delta in the good direction), `ACWorse` =
`ACDeltaNeg` (the bad direction), `ACRankOne/Two/Three` (cell backgrounds),
`ACInk`, `ACMuted`, `ACLink`, `BrickRed`.

Drawn from its own RNG stream, so adding the axis did not shift what any earlier
seed drew on the other thirteen. Files: `template/blocks/palettes/<value>.tex`,
copied to `paper/palette.tex` and input by `preamble.tex` after the defaults.

**Colour is never the encoding.** The good/bad direction is *also* carried by the
sign and by `\up` / `\down`; best is *also* carried by `\best`. A greyscale print
of any paper in this family loses no meaning.

### 15. `overview` — the shape of the system figure

Every paper in the family used to carry the same three boxes and two arrows.
The seven do not: P2 opens its two contributed components in sub-panels, P3 and
P6 wrap the body text around a narrow sketch, P6 splits architecture from
applications, P7 spends a second figure zooming into the key module.

| value | papers | what it is |
|---|---|---|
| `linear-pipeline` | generic (P1 without its artwork) | numbered stages left to right, a dashed box around the stages that differ across arms, frozen / trained badges; optionally a worked instance below (a shared ruler, two compared rows) |
| `stacked-panels` | P2 | a pipeline row, then two titled sub-panels (a) and (b) opening up the contributed components as small diagrams of their own sub-steps; caption is a paragraph |
| `wrap-compact` | P3, P6 | a narrow `wrapfigure` the body text flows around, short caption; the one grammar the density pass below does not apply to |
| `arch-plus-flows` | P6 | left, the architecture as a vertical stack (optionally ending in a shared-evidence comparison); right, the numbered ways the trained object is used, with only this paper's own flow opened into a sub-chain |
| `mechanism-zoom` | P7 | the pipeline row, and under it a zoom into the module this paper contributes, optionally worked on a handful of ranked items below |

All five are **Tier C**: boxes, arrows, badges, labels. None implies a
magnitude and none stands in for artwork that does not exist, so the figure is
honest in a paper whose evidence is numbers. Files:
`template/blocks/overview/<value>.tex`, copied to
`paper/figures/method_overview.tex`.

**Density.** The four full-width grammars carried only 13-19 drawn objects
each before Sep 2026, thin enough that a reader comparing the output against
real papers called it a flowchart rather than a designed figure. A density
pass took each to 40-51 (measured on one real instantiation per grammar,
`paper-batch-v2/S03-speculative-decoding`, `S10-fewshot-segmentation`,
`S26-pointcloud-registration`, `S16-timeseries-contrastive`, and
`paper-batch-v3/P247-ovd-shift`) by adding a WORKED INSTANCE below the
pipeline row: a shared ruler of positions or items reused by every compared
row, a cell's status drawn as its own fill and glyph, and -- when the
mechanism makes a per-item decision -- a small feature-to-decision cluster.
Targets are 45-60 objects on a near-page-width float and 30-45 on a narrow
one; `wrap-compact` is narrower still and its own honest ceiling was closer
to 8. None of this is a quota: density has to come from real structure the
method already has, never from decoration, and a grammar with nothing
repeated to index is a complete, honest, shorter figure without it. The
worked-instance vocabulary (`acitem`/`acitemkeep`/`acitemdrop`/`acitemgate`/
`acitemna`, `acruler`, `acrowlabel`, `acfeat`) lives in `preamble.tex`
alongside the rest of the shared styles below, and each grammar file's own
header comment says which paper proved it and what was tried and dropped.

Shared vocabulary lives in `preamble.tex`. The first set draws structure:
`acstage`, `acgroupbox`, `acpanel`, `acflow`. The second set is what the seven
source papers have that a flowchart does not, and was added after a reader
looked at a generated figure and said it was too plain — *"a lot of the icons
are missing"*:

| style | draws | measured from |
|---|---|---|
| `accard` | a stage: an icon, a bold name, a muted line of what it does | P1, P5, P7 |
| `acdeck` | the same card as an offset deck, for a stage that repeats | P5 |
| `actrap` | a trapezium, the conventional encoder/decoder shape | P5, P7 |
| `acours` / `acbase` | tinted regions: what this paper contributed, what every arm already had | P1, P7 |
| `aclegend` | the key, in a corner, never floating | P5, P7 |
| `actag` | the small uppercase label naming a region or a state | P1, P7 |
| `acstat` | the second arrow language: statistics, not representations | P5 |
| `acitem` / `acitemkeep` / `acitemdrop` / `acitemgate` / `acitemna` | a per-item cell at a ruler position; the variant IS the cell's status | density pass, Sep 2026 |
| `acruler` / `acrowlabel` | a shared position label; a row's own name against the ruler | density pass, Sep 2026 |
| `acfeat` | a small labelled node for one summand, statistic, or sub-step | density pass, Sep 2026 |

and four glyphs no icon font supplies: `\actokens{n}` (a representation drawn
as a token strip rather than named), `\acstack{n}` (a repeat drawn rather than
counted), `\acgrid{n}` (a score matrix), `\acop{W}` (a circled operator, the
way P7 keys its two concatenations).

What stays out, and why: **photographic thumbnails** (P1 puts a real vehicle
and flower inside its framework figure, P7 real video frames) and **3D
renders** (P7's point cloud). Both need real imagery. None exists for a
generated paper and `figure-ladder.md` forbids inventing it. The icon layer is
the substitute, not an equivalent.

### 16. `mark` — whether a project mark sits beside the title

`true` in P1, P3, P7; `false` in P2 and P5, whose titles start at the margin.
Drawn at roughly 55/45. Only `neurips1` has a title block that can carry one.
`paper/design.tex` writes `\DesignMarkfalse` when it is not drawn.

### 17. `icons` — the five glyphs the system figure leads with

An overview grammar never names a glyph. It names a role, and the role is a
macro the design fills: `\acIconInput`, `\acIconModel`, `\acIconMech`,
`\acIconOut`, `\acIconEvid`. Each is drawn from its own role-scoped list, on
its own random stream, and two roles never draw the same glyph — the same icon
twice in one figure reads as a link between two stages that are not linked.

Two more are fixed rather than drawn, because their meaning is conventional and
a reader should recognise them before reading the legend: `\acsnow` for a stage
that is not updated during training, `\acflame` for one that is.

Glyphs come from FontAwesome 5 Free via `fontawesome5`, loaded **guarded**: a
TeX tree without the package still builds a complete paper with every icon
rendering as nothing. The full role lists, the three house glyphs and the rules
for overriding one are in `references/figure-icons.md`.

Every name on those lists was verified by compiling it. `\ifcsname` is not a
sufficient test: `fontawesome5` keeps deprecated aliases (`\faExchange`,
`\faShield`, `\faSliders`) whose glyphs are absent from the Free set and which
raise a package error at use. `check_paper_structure.py` enforces the list.

## Coherence constraints

Hard — no draw violates these; each is a pairing every one of the seven respects:

```
cvpr2       ⇒ opening ∈ {none, results, results-wide}      (composite is single-column only)
iclr1       ⇒ citations author-year; devices may include llm-usage
sectioned   ⇒ appendix = supp-toc                            (P4 binds them)
by-task     ⇔ ablation = none                                (P1)
opening=none ⇒ overview figure by page 4                     (P5, P6)
related=appendix ⇒ a stub paragraph remains in the main body (P4, P6)
opening=composite ⇒ layout = neurips1                        (P3)
```

Soft — observed pairings, used as draw weights (×3), never forced:

```
by-task               ~ delta-rows
qual-quant-ablation   ~ wo-rows, grouped-rules, research-questions
setup-ablation-sota   ~ cumulative, roadmap
roadmap-setup-results ~ rotated-dense, default-delta, components, related=appendix
bold-lead-stream      ~ plain-bold, deep, prior-limitations
dense                 ~ principle, family-tint, setup-main-qual-ablation
sectioned             ~ rank-colors, naive-vs-ours, efficiency-scatter, symbols-table, preliminaries
```

## Word envelopes by layout

Measured from the seven; the gate uses the envelope of the drawn layout.

| section | `neurips1` / `iclr1` | `cvpr2` |
|---|---|---|
| Abstract | 140–260 | 150–260 |
| Introduction | 420–950 | 500–950 |
| Related Work (main body) | 0 or 300–650 | 0 or 250–600 |
| Method | 1100–2100 | 1000–1750 |
| Experiments | 600–1400 | 700–1500 |
| Conclusion | 130–320 | 120–290 |
| Main body total | 3400–5200 | 3600–4600 |
| Appendix | by `appendix` value: none / lettered ≥ 800 / deep ≥ 1500 / supp-toc ≥ 2000 / single ≥ 250 | same |
| Distinct cited keys (whole paper) | ≥ 35 | ≥ 40 |

## Reading a design

`paper.json` after `design_paper.py`:

```json
"design": {
  "seed": 4127, "layout": "cvpr2", "opening": "results-wide",
  "contributions": "bullets", "related": "subsections", "method_open": "formal",
  "equations": "moderate", "experiments": "qual-quant-ablation",
  "main_table": "grouped-rules", "ablation": "wo-rows",
  "qualitative": "small-multiples", "appendix": "separate",
  "limitations": "conclusion-paragraph", "devices": ["research-questions"],
  "palette": "tol-muted", "overview": "stacked-panels", "mark": false,
  "evidence": {"arms": 4, "conditions": 5, "primary": "ours"}
}
```

`DESIGN-BRIEF.md` in the project root restates the draw in prose for the
writer, with the concrete shape each section must take. The writer follows
the brief; the gates check the manuscript against the same draw.
