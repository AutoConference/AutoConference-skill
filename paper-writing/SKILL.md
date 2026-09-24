---
name: paper-writing
description: Turn gate-passed evidence into a submission-shaped LaTeX paper whose layout, tables, equations, citations, and prose are checked mechanically. Use when drafting, revising, compressing, or reviewing a manuscript, or when a paper must be brought to submission quality. Does not run experiments and does not decide what the evidence supports.
---

# Writing a paper that survives being checked

You turn evidence into a manuscript. You do not produce evidence, and you do not
decide what it supports. Those belong to whatever runs the experiments; the line
between you is `../interfaces/evidence-interface.md`, and it is not yours to move.

A paper is not finished when it reads well. It is finished when it reads well
**and** five gates pass on the compiled artifact. Structure, tables, equations,
citations, prose patterns, and the rendered page itself are all mechanically
checkable, so they are checked rather than remembered.

## The contract

`references/paper-writing-template.md` is the layout contract. It is measured
from the complete arXiv LaTeX source of arXiv:2506.21656v3, not estimated from a
rendered page, and it is not optional. Load its companions as the work reaches
them:

| File | Load when |
|---|---|
| `references/paper-writing-template.md` | always, first |
| `../interfaces/evidence-interface.md` | reading aggregates or a readiness verdict |
| `references/section-playbook.md` | drafting or revising any section |
| `references/table-grammar.md` | creating or editing any table |
| `references/equation-grammar.md` | writing the method or any display math |
| `references/figure-ladder.md` | deciding what visuals the evidence supports |
| `references/figure-icons.md` | filling the system figure, or changing one of its glyphs |
| `references/prose-rules.md` | any manuscript-facing prose pass |
| `references/audit-protocol.md` | the independent review round |
| `references/source-selection.md` | maintaining this skill |

## Setup

The template under `template/` is a **family**, not one scaffold. Sixteen
design axes — layout, opening figure, contribution list, related-work
placement, method opening, equation register, experiments organization,
table grammar, ablation grammar, secondary figure, appendix, limitations,
devices, palette, system figure, title mark — each take values measured from
one of seven real papers (the palette values are published colour schemes)
(`references/design-axes.md`). `scripts/design_paper.py` draws one coherent
combination for a seed, records it in `paper.json` under `design`, assembles
`paper/` from the drawn blocks, and writes `DESIGN-BRIEF.md` stating the
shape every section must take. Every gate then checks the manuscript against
*that* draw, not against a single exemplar.

```bash
python3 <skill>/scripts/design_paper.py --seed 4127 --layout draw --evidence runs/
#   --layout neurips1|iclr1|cvpr2   choose the venue instead of drawing it
#   --prefer opening=results        override one axis (refused if incoherent)
#   --dry-run                       print the draw, write nothing
```

Same seed + same evidence + same options reproduces the same design. Read
`DESIGN-BRIEF.md` before writing a word: it names the layout, what page 1
carries, how the experiments are organized, which table grammar the main
table uses and where its caption sits, and the word envelopes for that
layout. Never create a second LaTeX tree, and never draft in Markdown and
translate afterwards.

`paper.json` holds everything project-specific: the venue and page budget
(set by the draw), the design, and any figure bindings. `paper/design.tex` is
generated and carries the draw into LaTeX; do not edit it.

## The gates

All five are read-only and none of them edits the manuscript. Each reads
`paper.json` → `design` when present and checks against the drawn design.

```bash
python3 <skill>/scripts/check_paper_structure.py --paper-dir paper \
    [--submission] [--pdf output/pdf/paper.pdf --max-main-pages 9]
python3 <skill>/scripts/check_prose_quality.py paper/
python3 <skill>/scripts/check_citations.py paper/references.bib
<skill>/scripts/build_paper.sh --paper-dir paper [--final]
<skill>/scripts/render_paper.sh --pdf output/pdf/paper-draft.pdf
python3 <skill>/scripts/check_render.py output/pdf/paper-draft.pdf
```

`check_paper_structure.py` verifies section order, per-section and main-body
word budgets, equation count and labeling and narration, table caption
position and rule style, per-column decimal consistency, that a bolded or
underlined table cell is the column's actual best or second-best value under
the direction its caption declares, figure caption position and manifest,
forbidden placeholder strings, cross-reference closure — confirmed against the
compiled `main.aux` (and its build log) when `paper/build/` exists, not source
text alone — `\cite`-to-bib resolution, that every number in the abstract and
conclusion is reported by some float (a table's header cells count too), and,
given a PDF (effectively required in `--submission` mode), the page count and
page roles.

`check_prose_quality.py` is LaTeX-aware. It enforces the em-dash budget,
throat-clearing openers, third-person manuscript narration, process language,
unmeasured hype, sentence-rhythm runs, abstract numeric density, and terminology
stability through `paper/macros.tex`.

`check_citations.py` resolves every bibliography entry against arXiv or
Crossref and compares the returned title with the stored one. A fabricated
citation compiles, renders, and reads correctly; this is the only gate that
catches it.

`check_render.py` reads the compiled PDF, not the source: a literal `??` from
an unresolved cross-reference, two pieces of text whose boxes substantially
overlap, and a word running past the document's own established margin. It
exists because a page-1 teaser with overlapping text and a paper with a
printed `??` both compiled clean, rendered, and passed every one of the other
four gates — nothing upstream of it ever looks at the rendered page. Run it
against the same PDF `render_paper.sh` just produced.

Both structure gates are calibrated against the exemplar's own published source,
which passes with zero errors. A gate failure means the manuscript deviates from
a real accepted paper, not that the gate is too strict. `check_render.py` is
calibrated differently, against real rendering defects rather than exemplar
prose; see its module docstring and `references/audit-protocol.md`.

## Two mechanisms

**Slots.** Every value evidence must supply is written `\slot{...}`. A draft
build renders it as a grey marker; a `--final` build raises a LaTeX error on the
first one it meets. A placeholder cannot reach a submission artifact by
oversight. Fill a slot only from an aggregate, never from prose, memory, a
narrative Markdown file, or an agent log.

**The figure ladder.** Tables and equations are mandatory. Figures degrade:
designed artwork, then pgfplots from a real data file, then structural TikZ that
implies no magnitude, then omission. A guarded float disappears together with
the sentence that narrates it when its data file is absent. A figure that cannot
be built from real data is deleted and the prose reflows. Nothing ever renders a
box that says `TBD`.

## Workflow

### 1. Read the verdict

Read the readiness verdict described in `../interfaces/evidence-interface.md`.

- `READY`: proceed to the full workflow.
- `BLOCKED`: you may draft, compile a draft, and run every gate. You may not
  emit `PAPER_READY` and may not run `--final`. Report what the verdict says is
  missing. Do not narrow the paper into an internal note to get around it unless
  the operator asks for that explicitly, and say so when you do.

A polished paper cannot repair a weak evidence chain.

### 2. Plan

Freeze the story before prose: the one-sentence finding, the contribution list,
the claim-to-section map, the float plan, the appendix manifest, and the
per-section word budgets from the layout contract §1.

Keep four responsibilities separate even when you own all of them. Evidence
design decides what a comparison means. Writing turns supported claims into an
argument. Visual design makes supplied evidence legible without changing it.
Review diagnoses without rewriting in the same pass.

### 3. Floats before prose

Decide the visual tier first, using `references/figure-ladder.md`.

The system figure is not optional and is never blank: axis 15 has no `none`
value, so every design draws one of five grammars into
`paper/figures/method_overview.tex`. Fill its `\slot{}`s like any other block.
Its glyphs come from five role macros the design already drew; if one is wrong
for this paper's domain, renew it once in `paper/macros.tex` from the lists in
`references/figure-icons.md`. Do not write a glyph name into the figure itself.

1. Generate `paper/data/*` from the aggregates:
   `make_paper_data.py --config paper.json --opening runs/aggregate__*.json --primary <arm> [--direction up|down] [--metric <name>]`.
   This writes the opening figure's data (bars with per-condition deltas, a
   radar when there are five or more conditions) and the secondary figure's
   data for whichever grammar the design drew. A plotted value and a tabled
   value then cannot disagree. Two aggregates that share a `method` but
   report different metrics are refused until `--metric` says which one the
   figures read.
2. Fill `paper/tables/main_results.tex` in the grammar the design drew
   (`references/table-grammar.md` has all six) and `paper/tables/ablations.tex`
   in its ablation grammar. Use the semantic markers `\best`, `\second`,
   `\rankone`…, `\deltarow`, `\worse`, `\deltacell`; the design renders
   them.
3. Fill `paper/figures/opening.tex`'s slots (only `composite` has any) and the
   secondary figure's caption slot; delete nothing the design installed.
4. Write the captions now. A caption you cannot write is a float you do not need.

Every quantitative visual carries a `% source-data:` / `% generator:` manifest.
Never draw a chart from values copied out of prose.

### 4. Write

In this order, never front-to-back:

```
Experiments and float captions -> Method -> Introduction -> Related Work -> Conclusion -> Abstract
```

Front matter written first promises a paper the results do not support. Follow
`references/section-playbook.md` for each section's moves and budget,
`references/equation-grammar.md` for every display, and `references/prose-rules.md`
for voice, banned patterns, and the five revision passes.

- Never invent a BibTeX entry. Fetch verified metadata, or leave the citation
  open and let the gate block.
- Keep terminology stable through `paper/macros.tex`. Renaming a concept happens
  in one place.
- Remove reviewer simulation, process narration, hype, and generic caveats.
  Preserve material failures, assumptions, and limitations.
- A full-paper request produces a full paper near the target budget, not an
  abstract plus an outline. A section under budget is missing an argument move;
  expand with mechanism, setup, and analysis, never with padding.

### 5. Compile, measure, inspect

Run the gates as one command, from the project root:

```bash
<skill>/scripts/gate.sh            # final build + render + all four checkers, budget read from paper.json
<skill>/scripts/gate.sh --draft    # while slots are still open
```

Then fix **every ERROR** it lists and run it again. Do not run the checkers
one at a time after each small edit: a paper that is gated after every
paragraph gets fifty builds instead of five and finishes no sooner.

What the severities mean, so they do not become busywork:

- **ERROR** blocks. Fix it.
- **WARNING** is a probable defect. Read it; fix it if it is one; leave it and
  say why if it is not (a hyphenated method name that contains a macro's
  term, for instance).
- **ADVISORY** is information: an open slot, a long sentence, a semicolon
  rate, an unused bibliography entry. Do not iterate on advisories. A paper
  is not better for having driven its advisory count to zero.

Budgets are planned once, not grown by increments: `DESIGN-BRIEF.md` gives
every section's envelope for this layout; write each section to its target
before the first build, and let the gate confirm rather than discover.

An overfull `\hbox` in the build log is a defect. After the gates pass,
look at page 1, every float page, the reference transition, and every
appendix page in `output/pages/` at full resolution. No gate reads the drawn
shapes: text under an opaque box, a label clipped by a border, a legend on
top of a bar are found only by looking.

### 6. Independent audits

Run the four fresh-context audits in `references/audit-protocol.md`: numeric and
claim, citations, scientific review, and visual format. Auditors receive the
artifact and the evidence, never the writer's rationale. Limit the
review-fix-recompile cycle to two focused rounds; a third requires a new
concrete blocker, not stylistic churn.

### 7. Completion gate

```bash
<skill>/scripts/gate.sh
```

Emit `PAPER_READY` only when every condition in `references/audit-protocol.md`
§ Completion gate holds and the readiness verdict says `READY`. Otherwise emit
`PAPER_BLOCKED` naming the exact missing evidence or defect.

## Autonomous operation

Paper mode is terminal. It ends with `PAPER_READY` or `PAPER_BLOCKED`, and it
does not start unrelated work afterwards. If a gate blocks, report the blocker;
do not lower the artifact to clear it.

Read `DESIGN-BRIEF.md` first and the reference files when the workflow step
that needs them arrives (the table in "The contract" says which). Reading
all 1,700 lines of references before writing a word is a fifth of a paper's
effort spent before the paper exists.
