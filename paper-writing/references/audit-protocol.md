# Audit protocol

Independent review of the compiled artifact. Load in paper mode step 6.

These prompts live here, not in the manuscript. Audit instructions, gate
transcripts, and agent logs are internal process material; putting them in the
appendix makes the paper a report about its own production.

## Independence rule

Auditors judge the artifact and the evidence package. They do not receive the
exemplar notes, the writer's rationale, the intended score, the claim the writer
hoped to make, or any earlier self-review. An auditor told what the answer
should be is not an auditor.

Run the four audits below on a fresh context each. Limit the
review-fix-recompile cycle to two focused rounds; a third round requires a new
concrete blocker, not stylistic churn.

## Order

`scripts/gate.sh` runs the whole sequence below with the right flags; the
commands are listed so an auditor can run one gate alone.

The gates read the drawn design from `paper.json`; a paper assembled by
`design_paper.py` is checked against its own layout's envelopes, its own
table grammar's caption position, and its own equation register.

Run the deterministic gates first. They catch everything mechanical, so the
human-judgment audits are not spent on decimal precision.

```bash
python3 scripts/check_paper_structure.py --paper-dir paper --submission \
    --pdf output/pdf/paper.pdf --max-main-pages <venue limit>
python3 scripts/check_prose_quality.py paper/
python3 scripts/check_citations.py paper/references.bib
scripts/build_paper.sh --paper-dir paper --final
scripts/render_paper.sh --pdf output/pdf/paper.pdf

# Re-run after the build: the structure gate's cross-reference check reads
# paper/build/main.aux, so the first pass above (before any build exists, or
# against a stale one from a prior round) cannot confirm that a \ref actually
# resolved in the artifact that will ship -- it degrades to a warning instead
# of silence, but a warning is not the same as a confirmed pass.
python3 scripts/check_paper_structure.py --paper-dir paper --submission \
    --pdf output/pdf/paper.pdf --max-main-pages <venue limit>

# The one gate that reads the artifact instead of the source. Every check
# above this line can pass on a manuscript whose compiled page prints "??",
# or whose page-1 teaser has two boxes drawn on top of each other -- both
# shipped past all four text gates in separate real drafts before this
# existed.
python3 scripts/check_render.py output/pdf/paper.pdf
```

`check_render.py` reads word boxes, so it is blind to text hidden under a
drawn shape, to a float overflowing only the bottom of a page, and — in a
two-column layout — to one overflowing only the gutter between the columns.
Those are what looking at `output/pages/` is for, and why the completion gate
asks for page 1, every float page, and the appendix.

Only then run audits 1-4.

## Audit 1 — numeric and claim

**Input.** The intended headline claims, `results.tsv`, primary run JSONs,
sidecar manifests, aggregate artifacts, and the compiled PDF.

1. **Primary provenance.** Every cited aggregate enumerates existing primary
   inputs with method, split seed, trajectory seed, full configuration, and
   source commit.
2. **Statistical scope.** Compared methods have equal coverage. Reject any
   general claim resting on a single split, a single trajectory, or a selected
   before/after pair.
3. **Manuscript consistency.** Every number in the abstract, prose, tables,
   figures, captions, and conclusion matches the aggregate artifact, to the
   last decimal.
4. **Float consistency.** Every plotted point and table cell regenerates from a
   listed aggregate. Units, precision, metric direction, split coverage,
   trajectory count, and missing-value semantics agree across figure, caption,
   table, and surrounding text.
5. **Scope.** Title, abstract, introduction, and conclusion name the actual
   dataset and experimental scale wherever the evidence does not establish a
   broader phenomenon.

**Hard rejections.**

- A narrative file, remembered value, or chat log used as evidence.
- A derivative JSON that omits its primary input manifest.
- A single run or a selected pair described as a distribution.
- Unequal split or trajectory coverage between compared methods.
- An abstract or conclusion number absent from the main table.
- A figure or table value that cannot be regenerated from source data.

**Output.** A claim ledger with columns `claim, scope, primary inputs,
aggregate, uncertainty, contradictions, verdict, required action`, then exactly
one terminal token: `PAPER_READY` or `PAPER_BLOCKED`.

## Audit 2 — citations

`check_citations.py` already resolved every entry against arXiv or Crossref and
compared titles, so existence and metadata are settled before this audit starts.
What remains is the part a resolver cannot judge: for every `\cite` key, whether
the sentence citing it is supported by what that work actually says. Flag any entry that could not be verified against a primary
source. Flag statistics cited only through a review or textbook.

Check `references.bib` for entries that are never cited.

## Audit 3 — scientific review

Review under the target venue's rubric, as a reviewer would.

- Does each claim in the introduction have evidence in the experiments?
- Are there logical gaps between mechanism and result?
- Is related work sufficient and correctly positioned?
- Are the statistics appropriate for the sample sizes reported?
- Would a skim reader recover the contribution from the title, abstract,
  introduction, and whatever the design drew onto page 1 alone?

Judge claim calibration in both directions. Recommend narrowing when scope or
modality exceeds the evidence; recommend *removing* hedges stacked around a
supported result. Flag self-defense ("we do not claim"), instruction
confessions ("we do not address X"), and generic caveats outside Limitations as
writing defects. A tone fix must never alter facts, negation, modality, scope,
comparison direction, or numbers.

For each issue: severity (CRITICAL / MAJOR / MINOR), location, and the fix.
Apply CRITICAL and MAJOR; report MINOR to the operator.

## Audit 4 — visual and submission format

`check_render.py` already caught what it can from the compiled PDF directly:
a printed `??`, two pieces of text drawn on top of each other, a word past
the page's own margin. That is a mechanical floor, not a substitute for this
audit — it does not judge readability, contrast, grayscale, orphaned
headings, or whether a bolded number is actually the best value in its
column. Render every page and inspect at full resolution. Reject:

- clipped or overlapping content;
- unreadable figure text at print scale;
- orphaned headings and stranded floats;
- inconsistent numeric precision between a figure and its table;
- low-contrast tints, or a figure that fails in grayscale;
- undefined citations or references;
- page-budget overflow;
- any surviving template artifact.

Text extraction cannot validate layout. Look at the pages.

## Completion gate

`PAPER_READY` requires all of:

- both deterministic gates pass in `--submission` mode;
- the `--final` build compiles, so no `\slot` remains;
- every abstract and conclusion number traces to an aggregate;
- every headline claim has adequate split and trajectory support;
- no later result contradicts the chosen story;
- limitations name reduced scale, dataset scope, seed and trajectory variance,
  and any evidence loss;
- the page budget fits and visual inspection finds no defect;
- `check_render.py` passes clean against the `--final` PDF — no printed `??`,
  no overlapping text, nothing past the margin;
- all four audits return no CRITICAL or MAJOR issue.

Anything else emits `PAPER_BLOCKED` naming the exact missing evidence or
defect. A blocked paper is a correct outcome, not a failure to route around.
