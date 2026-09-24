# Section playbook

Per-section moves, budgets, and opening patterns, measured from the arXiv:2506.21656
source. Load this whenever drafting or revising a section.

Every count below is that paper's. **`DESIGN-BRIEF.md` outranks all of them**:
it carries the word envelope for the drawn layout, the equation floor for the
drawn register, the drawn organization of Experiments, the drawn placement of
Related Work and Limitations, and the drawn appendix and its floor. Read the
moves here; take the numbers from the brief.

Write in this order, never front-to-back:

```
Experiments and float captions -> Method -> Introduction -> Related Work -> Conclusion -> Abstract
```

Front matter written first promises a paper the evidence cannot deliver. The
abstract is a summary of a finished argument, so it is drafted last.

---

## Abstract

One paragraph, 140–190 words, no citations, no undefined acronyms, no display
math, no `\cite`. Five moves in this order:

1. **Problem.** The scientific difficulty, in the paper's own terms.
2. **Gap.** What remains unresolved and why prior work does not settle it.
3. **Design or method.** What this paper does, named with canonical macros.
4. **Evidence.** The single strongest supported result, with its uncertainty.
5. **Bounded conclusion.** What this establishes and over what scope.

Constraints:

- Every number here also appears in the main results table. No exceptions.
- No more than two numeric comparisons. An abstract that is mostly numbers has
  replaced the contribution with a results dump; rewrite it around the science.
- Self-contained: readable without the rest of the paper.
- If a headline claim is not gate-passed, the abstract states the narrower claim
  the evidence supports. It never states the ambition and hedges afterwards.

## Introduction

420–650 words in four paragraphs, then a contribution list of 2–4 items.

| Paragraph | Job |
|---|---|
| 1 | The scientific problem and why it matters. Cite the field, not the paper. |
| 2 | The specific unresolved observation, and why existing evidence cannot explain it. Turn on the hinge: "However, ..." |
| 3 | What this paper separates, controls, or introduces that makes the question answerable. Name the mechanism, not just the method's name. |
| 4 | The supported result and its scope. Preview the strongest number here; do not save it for §5. |

Contribution list: `\begin{itemize}[itemsep=0.5ex, parsep=0pt, topsep=0pt]` with
`\item[\textbf{(1)}]` markers. Each item is one falsifiable sentence naming a
contribution and the evidence class that supports it. Two contributions honestly
supported beat four padded ones.

Prohibited here: agent-process narration, defensive novelty positioning,
anticipated-reviewer arguments, and roadmap paragraphs that restate the table of
contents. The method must be readable by page 2–3.

## Related Work

Organize by **scientific relationship**, not paper by paper. The brief says how
long and in what shape: two or three bold inline themes, numbered subsections,
or — with `related=appendix` — one main-body paragraph naming the families and
pointing at the full appendix section.

The exemplar uses three bolded inline themes, each `\textbf{Theme Name.}`
followed by a single dense paragraph. Reproduce that shape:

- one paragraph per theme, 2–4 themes;
- each paragraph summarizes a line of work, then positions this paper against it
  in its final sentence;
- close the section with the precise gap this paper fills.

Do not write mini-summaries of individual papers, and do not list citations
without synthesis. A citation appears because it changes what the reader should
believe, not because it exists.

## Method

Three or four subsections. The brief gives the word envelope and the equation
floor for the drawn register; `equations=none` is a real draw (P6) that carries
the method in prose and the overview figure, with all math inline.

Structural requirements:

1. **The overview figure is the first thing in the section**, before any prose
   subsection. `\input{figures/method_overview}` immediately after
   `\section{Method}` and its `\label`.
2. **First subsection is formulation**: define the task, the notation, and the
   objects the paper reasons about. Introduce the central tuple or objective
   inline with `$...$`, not as a display, so the section opens with reading
   rather than with a wall.
3. **Middle subsections carry the mechanism.** Each opens by naming the problem
   with the existing approach, then states what this paper changes and why.
4. **Equations are narrated.** See `references/equation-grammar.md`. The pattern
   is: sentence that motivates → display → `where`-sentence that defines every
   new symbol → sentence that states the equation's experimental role.
5. **Principles or design rules**, when a choice needs justification, are set as
   a bold label followed by an italic one-sentence statement, then a paragraph
   of evidence for it. The exemplar uses exactly this device twice.
6. **Derivations move to the appendix.** Main-body math is what the reader needs
   to understand the claim.

For an empirical study rather than a new algorithm, the subsection sequence is:
task and bound formulation; the configurations compared; the factor
decomposition that makes them comparable; the aggregation and statistics.

## Experiments

The brief names the drawn organization — one subsection per task, setup →
main → qualitative → ablation, a bold-lead results stream, and four more — and
that organization decides the subsections and their order. The moves below are
what those subsections do, in the order they normally appear:

1. **Experimental setup.** Before any result: data, fixed evaluation semantics,
   scale, method identity, split seeds, trajectory seeds, uncertainty estimator,
   hardware, and failure handling. Point implementation detail to the appendix.
2. **Main results.** `\input` the main table first, then the prose that reads it.
   Each paragraph answers one question — effectiveness, causality,
   generalization, efficiency, robustness, or a scope boundary — and names the
   comparison it is making.
3. **Qualitative or distributional analysis.** Clearly labeled as examples when
   it is examples. A single trajectory is never an ablation result.
4. **Ablations and sensitivity.** Paired minipage tables, then the paragraph
   that explains what each swept parameter does and where the mechanism breaks.

Baseline families are introduced with tinted inline labels that match the row
tints in the table, so the reader learns the color key in prose and reuses it in
the table. See `references/table-grammar.md`.

Never present results as disconnected numbers. Every number in prose is bolded
only when it is the paper's own headline delta, and it must match the table to
the last decimal.

## Conclusion

180–320 words, one or two paragraphs. Restate only gate-passed claims. Name the
evaluated dataset and scale. Introduce no new number, no new recommendation, and
no universal language. Close with future work that is specific to the dimensions
this study could not settle.

`\section*{Acknowledgments}` follows the conclusion when the submission mode
permits it, and is removed for anonymous review.

## Appendix

`\appendix`, then the sections the drawn appendix calls for: `lettered`,
`deep` (each study as X.1 setting / X.2 details / X.3 analysis), `supp-toc` (a
supplementary title page with `\tableofcontents`), `single`, or `none` at all.
The brief carries the word floor for the drawn value. The exemplar runs seven
lettered sections. Default manifest for an empirical study:

- **A.** Bound and evaluation details
- **B.** Exact configuration and environment
- **C.** Run manifest and provenance schema
- **D.** Complete per-seed and per-trajectory tables
- **E.** Additional examples and observed failures
- **F.** Statistical procedures and sensitivity checks
- **G.** Broader impacts, when the venue requires it
- **H.** Limitations

What belongs here: exhaustive configurations, full tables, prompts, rubrics,
proofs, additional examples. What stays in the main body: the evidence and the
method a reader needs to believe the claim.

## Reverse-outline test

After all sections are drafted, extract the first sentence of every paragraph and
read them in sequence. They must form a coherent argument on their own. If a
topic sentence does not advance the story, rewrite the paragraph rather than
adding a transition. Then check both directions:

- every claim in the abstract and introduction has evidence in Experiments;
- every float in Experiments supports a stated claim.

A float that supports nothing, and a claim that no float supports, are both
defects.
