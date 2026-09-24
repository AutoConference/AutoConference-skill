# Layout contract: the executable paper standard

Primary exemplar: *Fine-Grained Preference Optimization Improves Spatial
Reasoning in VLMs*, arXiv:2506.21656v3. Both the 25-page PDF and the complete
arXiv LaTeX source (`neurips_2025.tex`, `sections/*.tex`, `assets/tables/*.tex`,
`assets/figures/*.tex`, `neurips_2025.sty`) were read. Every number in this file
was measured from that source, not estimated from the rendered page.

Reuse the exemplar's document grammar: hierarchy, section order, budgets, float
cadence, table grammar, equation grammar, caption discipline, appendix roles.
Never reuse its wording, claims, model names, logo, figures, task examples, or
scientific content. See `## Do-not-copy boundary`.

This is the default internal layout contract. If a target venue imposes an
incompatible official template, the venue template wins on geometry and required
sections; everything else in this file still applies.

**The drawn design outranks every count in this file.** A paper assembled by
`scripts/design_paper.py` carries seventeen drawn axes in `paper.json` →
`design`, restated in `DESIGN-BRIEF.md`, and the gates check the manuscript
against *that* draw: its layout, its word envelopes, its equation floor, its
appendix floor, its section order. The numbers below are the exemplar's own
measurements. They are the fallback for a paper with no design, and everywhere
else they are context, not the rule. Where this file and the brief disagree,
the brief is right and this file is describing one member of the family.

Companion files, loaded on demand:

| File | Load when |
|---|---|
| `../interfaces/evidence-interface.md` | reading aggregates or a readiness verdict |
| `references/section-playbook.md` | drafting or revising any section |
| `references/table-grammar.md` | creating or editing any table |
| `references/equation-grammar.md` | writing the method or any display math |
| `references/figure-ladder.md` | deciding what visuals the paper can support |
| `references/prose-rules.md` | any manuscript-facing prose pass |

---

## 1. Measured budgets

These are the exemplar's actual word and float counts. They are the target
envelope, not a hard maximum. A section outside `±30%` of its target is a
structural defect: too short means the argument is missing a move, too long
means detail belongs in the appendix.

| Unit | Exemplar | Target envelope | Displays |
|---|---:|---|---|
| Abstract | 154 words, 1 paragraph | 140–190 | none |
| Introduction | 495 words, 4 paragraphs + contributions | 420–650 | contribution list, 2–4 items |
| Related Work | 503 words, 3 bolded themes | 420–650 | none |
| Method | 1724 words, 3 subsections | 1300–2100 | 10 numbered equations |
| Experiments | 688 words, 4 subsections | 600–1000 | 3 table inputs |
| Conclusion | 224 words + acknowledgments | 180–320 | none |
| Main body total | 3634 words | 3100–4300 | — |
| Appendix | 3376 words, 7 lettered sections | ≥ 1500 | 1 equation, 4 figures |
| Citations in main body | 70 `\cite` calls | ≥ 40 | — |
| Bibliography entries | 153 | every cited key, no bloat | — |

`scripts/check_paper_structure.py` measures these and reports every section
outside its envelope.

## 2. Page geometry and typography

The exemplar is NeurIPS 2025 single-column, not a two-column paper.

- US Letter, 612 × 792 pt.
- Text block 5.5 in wide × 9 in high, 1 in top margin.
- Times-compatible serif, 10 pt on 11 pt leading.
- Zero paragraph indentation, roughly 5.5 pt paragraph separation.
- Section heading 12 pt bold; subsection 10 pt bold.
- Figure captions below the float; table captions above the float.

Use the unmodified official `neurips_2025.sty`. Never reimplement its geometry,
and never edit the style file to win page space. Space is won by moving detail
to the appendix, not by shrinking type.

## 3. File map

The executable template lives under `paper/` and is filled in place. Do not
create a second LaTeX tree, and do not draft the manuscript in Markdown and
translate it afterwards.

In the project:

```
paper/main.tex            section order, title block, opening, abstract wiring
paper/preamble.tex        packages, palette, float defaults, slot machinery
paper/macros.tex          canonical terminology macros (see §9)
paper/<venue>.sty         official geometry, unmodified (the drawn layout's)
paper/design.tex          GENERATED switches carrying the draw into LaTeX
paper/data/opening.*      macros and plot data for the drawn opening figure
paper/data/*.dat          plot data, generated from aggregates
paper/figures/opening.tex the drawn page-1 opening (empty when opening=none)
paper/figures/*.tex       overview and results figures
paper/tables/*.tex        main, secondary, and paired ablation tables
paper/sections/*.tex      one file per section, in the order of §4
paper/references.bib      only keys actually cited
paper.json                venue, page budget, and figure specs
runs/aggregate__*.json    the evidence, written by the research side
```

In the skill:

```
template/                         the scaffold; copy once to paper/
config.example.json               starting point for paper.json
scripts/build_paper.sh            compile (--final enforces §9)
scripts/render_paper.sh           render every page to PNG for visual QA
scripts/check_paper_structure.py  layout, floats, slots, refs, numbers, pages
scripts/check_prose_quality.py    prose patterns
scripts/check_citations.py        resolve every entry against arXiv or Crossref
scripts/make_paper_data.py        aggregates -> opening macros and plot data
scripts/design_paper.py           draw a design, assemble paper/ from it
scripts/check_render.py           the compiled page: ??, overlap, margins
scripts/gate.sh                   run every gate once, in order
```

## 4. Section order

The spine, which no draw changes:

1. Abstract
2. Introduction
3. Related Work — a full section, or a short stub pointing at the appendix
   when the design drew `related=appendix`
4. Method
5. Experiments
6. *Ablation Study*, as its own top-level section, only when the design drew
   `experiments=separate-ablation-section`
7. Conclusion
8. Limitations, where the design puts it: its own unnumbered section, the last
   paragraph of the conclusion, an appendix section, or absent
9. Acknowledgments, when the submission mode allows them
10. References
11. Appendices, when the design draws one: `\appendix`, then its sections

**Do not add `\clearpage` before the references.** Several of the layouts
already break the page there, and the extra break ships a blank page; the page
gate accepts references that follow the text on the same page and counts that
page as main body. Writers have added this exact `\clearpage` to satisfy an
earlier version of this line and produced blank pages twice.

The exemplar's `main.tex` wires this with `\input` per section and nothing else
between them. Keep that: `main.tex` carries structure, sections carry prose.

## 5. Page rhythm

One member of the family, measured: the exemplar's own pagination. Read it for
the *roles* pages play, not as a target. Main content on PDF pages 1–10,
references on 11–17, appendices on 18–25. Within the main body:

| Page | Content |
|---|---|
| 1 | title block, author block, full-width teaser, abstract opening |
| 2 | abstract end, introduction, contribution list |
| 3 | related work, compact and thematic |
| 4 | method opens with the full-width overview figure |
| 5 | core method subsection, equations interleaved with interpretation |
| 6 | mechanism figure |
| 7 | second method subsection, remaining equations |
| 8 | full-width main results table at the top of Experiments |
| 9 | secondary table and qualitative or distribution figure |
| 10 | paired ablation tables, conclusion, acknowledgments |

Reproduce the *roles*, not the exact page numbers. What must hold:

- the drawn opening, when the design draws one, is on page 1, and the abstract
  does not spill past page 2 (with `opening=none` the abstract opens page 1 and
  the overview figure must appear by page 4);
- the method's overview figure appears before the method's first equation;
- the main results table is the first float in Experiments;
- ablations come after main results and qualitative analysis;
- the conclusion is the last main-body section, with no new numbers.

## 6. Front-page contract

The first page has one deliberate reading path. What sits in it is the drawn
`opening` axis, and `DESIGN-BRIEF.md` names the value and its grammar; the
figure lives in `paper/figures/opening.tex`, and every number in it is read at
compile time from `paper/data/opening.dat`. `references/figure-ladder.md` §
"The opening figure" is the full contract for the four drawn values.

The rest of this section describes the retired Question / Design / Finding
card (`figures/hero.tex`), which is drawn only when an operator forces
`--prefer opening=design-card` because the evidence cannot support a plot. The
title block above it, items 1 and 2, is the exemplar's and applies whenever the
drawn layout is `neurips1`.

1. A two-line, left-aligned bold title inside a centered title region, preceded
   by a project mark in a `m{1.32cm} m{12.10cm}` two-column `tabular`. The
   template's mark is drawn in TikZ, so page 1 needs no external image. Never
   reuse the exemplar's logo. **Each title line must fit 12.10 cm**, which is
   roughly 40 characters at the title size; a longer line overflows the column
   and the build reports an overfull `\hbox`. Shorten the title rather than
   widening the column.
2. Author, affiliation, email, and project-link lines: bold author names with
   superscript affiliation markers, then affiliations, then a `\texttt` email
   line, then an optional colored project URL. Centered and tightly stacked.
3. `\vspace{-6mm}`, then a full-width teaser figure, then `\vspace{-3mm}`.
4. The abstract immediately below the teaser.

The teaser carries **no numbered caption and no `\caption`**. Its in-figure
labels must be self-explanatory at print scale. It must communicate the paper
without body text, and it must contain:

- the question the paper answers, stated as a question;
- the design that answers it, shown as a matrix or a factor decomposition
  rather than selected endpoints;
- one supported takeaway with its uncertainty;
- a restrained visual key that later figures reuse.

Every number drawn inside the teaser comes from `paper/data/teaser.tex`, so the
teaser cannot drift from the results table. Numbers are never typed directly
into `hero.tex`.

## 7. Float grammar

Exemplar float inventory: 1 unnumbered teaser, 5 numbered main-body figures,
4 numbered main-body tables (one of which is a paired minipage table holding
two numbered tables), plus 4 appendix figures.

Rules:

- Tables: caption **above**, `[t!]` placement, `booktabs` rules, no vertical
  rules, no `\hline`. Full grammar in `references/table-grammar.md`.
- Figures: caption **below**, `[!t]` or `[t]` placement, `\linewidth` or
  `0.99\linewidth`. Caption opens with a bold lead phrase, then states what is
  shown, what is compared, and what to notice.
- One `wrapfigure` at most, at `0.65\textwidth`, and only for a genuinely
  compact secondary panel. Never wrap a dense plot or any table.
- Paired small tables use two minipages at `0.48` and `0.44` of `\textwidth`,
  each with its own caption and label, identical numeric precision on both
  sides.
- Never use `[H]`. Let the venue class place floats.
- Every quantitative visual carries a manifest naming its source data and its
  generation script. A chart is never drawn from values copied out of prose.

## 8. Guaranteed-content ladder

Figures degrade. Tables and equations do not.

| Element | Status | Rule |
|---|---|---|
| Main results table | **mandatory** | The paper does not exist without it |
| Secondary or paired table | **mandatory** | At least one beyond the main table |
| Numbered equations | by the drawn register | `equation_floor` in the brief: 0 for `none`, 9+ for `dense`. Each one narrated |
| Page-1 opening | by the drawn axis | `none` is a real draw (P5, P6); otherwise the panel is Tier B from `opening.dat` |
| Overview figure | expected | Tier C form is a TikZ box diagram |
| Data plots | best effort | pgfplots from a data file, or omitted |
| Raster artwork | optional | Omit rather than fake |

When a visual cannot be produced from real data, **delete the float and reflow
the prose**. Never ship a box that says `DATA SLOT`, `TBD`, or `Figure omitted`.
The tiers and their decision rule are in `references/figure-ladder.md`.

## 9. Slot discipline

`paper/preamble.tex` defines:

```latex
\newif\ifACfinal\ACfinalfalse
\newcommand{\slot}[1]{...}   % visible grey marker in draft, hard error in final
```

`\slot{...}` marks every value, name, link, or claim that evidence must supply.
In a draft build it renders as a grey bracketed marker. In a final build
(`scripts/build_paper.sh --final`) any surviving `\slot` raises a
LaTeX error and the build fails. That is the mechanical guarantee that no
placeholder reaches a submission artifact.

`paper/macros.tex` holds one macro per canonical term — method names, dataset
names, metric names. Prose uses the macro, never a hand-typed synonym. This
enforces terminology stability mechanically rather than by vigilance.

Every generated-value default in `paper/data/*.tex` must itself be
`\slot{...}`-wrapped, not a literal placeholder string. A hardcoded default
that reads as real content (`template/data/teaser.tex` once shipped
`\TSmetric` as the literal text `certified bound`, left over from an earlier
study) matches no forbidden string and no `\slot`, so skipping
`make_paper_data.py` leaves it in place silently: the paper compiles, passes
every gate, and ships the wrong value. Wrapping the default in `\slot{...}`
is what makes `--final` refuse it instead.

## 10. Cross-references and citations

Follow the exemplar's setup:

- `natbib` with `numbers,compress`; `\bibliographystyle{plainnat}`.
- `cleveref` with `nameinlink,capitalize,noabbrev`; sections render as `§N`
  through `\crefformat`; equations render as `Eq.`
- Reference every numbered equation that later prose depends on, and reference
  every float from the prose that interprets it. A float nothing points at is
  either mislabeled or unnecessary.
- Never invent a BibTeX entry. Fetch verified metadata, or leave the citation
  slot marked and fail the gate.
- `references.bib` contains only keys actually cited.
- A `\label` sitting in the source is not proof LaTeX registered it. A label
  split away from its `\caption` by a wrapper (a `threeparttable` around a
  `resizebox`'d `NiceTabular` has actually done this) can compile clean and
  print a literal `??` for every `\ref` to it while a source-only scan sees
  nothing wrong. `check_paper_structure.py` cross-checks every `\ref`/`\cref`
  against the compiled `main.aux` whenever `paper/build/` exists — run it
  again after `build_paper.sh` for that check to have a build to read.

## 11. Automated gates

Five, all read-only, all of which must pass before `PAPER_READY`. Run them
together — `scripts/gate.sh` builds, renders and runs every checker in the
right order with the page budget read from `paper.json`, and one line per gate:

```bash
scripts/gate.sh                  # the whole set, submission build
scripts/gate.sh --draft          # while still filling slots
scripts/gate.sh --skip-citations # when the network is not available
```

It runs, in this order: `build_paper.sh --final` (slot enforcement + compile),
`render_paper.sh` (page images for visual QA), `check_paper_structure.py
--submission --pdf ...` (layout, floats, slots, refs, numbers, pages, and a
re-confirmation that every `\ref` resolved in the build that will ship),
`check_prose_quality.py`, `check_citations.py`, and `check_render.py`.

`check_paper_structure.py` verifies: section order and presence; per-section
and main-body word budgets against §1; equation count, labels, and narration;
table caption position, rule style, absence of vertical rules, per-column
decimal consistency, and that a bolded or underlined cell is the column's
actual best or second-best value under the direction its caption declares;
figure caption position, bold lead phrase, and source manifest; that the drawn
opening matches its axis (`results` / `results-wide` numbered, captioned and labelled;
`composite` and the `design-card` fallback uncaptioned; `none` empty); forbidden placeholder strings; `\ref`/`\label` closure, confirmed
against the compiled `main.aux` (and its build log) rather than source text
alone whenever a build is available; `\cite` keys resolving in
`references.bib`; bibliography bloat; that every number in the abstract and
conclusion is reported by some float, including a number visible only in a
table's column header; and, given `--pdf` — effectively required in
`--submission` mode — the page count and the page roles.

`check_citations.py` resolves each bibliography entry against arXiv or Crossref
and compares the returned title with the stored one. A fabricated citation
compiles, renders, and reads correctly, so no other gate catches it.

Text extraction cannot validate layout. After every material edit, recompile,
re-render, and inspect page 1, every float page, the reference transition, and
every appendix page.

## 12. Do-not-copy boundary

Reusable: document grammar — hierarchy, section order, budgets, float cadence,
table and equation grammar, caption discipline, appendix roles, palette logic.

Not reusable: the exemplar's prose, title wording, model and method names,
logo and icons, task examples, dataset semantics, figures, or any scientific
content. Where the exemplar's concrete values appear in this file or in the
template, they are structural measurements, not content to import.
