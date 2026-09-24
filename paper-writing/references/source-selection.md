# External source selection for this skill

Snapshot reviewed on 2026-08-26; remote HEADs, skill counts, and license
metadata revalidated on 2026-08-27. The writing layer was re-derived on
2026-08-27 in a second pass that read the exemplar's complete arXiv LaTeX
source rather than only its PDF. This file records why ideas were selected or
rejected; it is not a runtime dependency list.

## CCFA-Skills

Repository: `mikubaka88/CCFA-Skills`
Commit: `fd5c7e3afcc097d874d296a0e1e8118ae597f847`
License: MIT

All 17 skill entrypoints were inventoried. The useful paper-facing subset was:

- `ccf-experiment-designer`: claim-first experiment and table semantics;
- `ccf-integrity-auditor`: claim/number/citation consistency;
- `ccf-paper-writer`: story-first full-manuscript drafting with page budgets;
- `ccf-humanization`: remove defensive/process prose without hiding evidence;
- `ccf-paper-reviewer`: separate diagnosis from rewriting;
- `ccf-paper-to-exemplar`: distill transferable moves without copying content;
- `ccf-visual-composer`: evidence-bound visuals and render QA;
- `ccf-submission-checker`: final format/build/artifact gate.

Integrated here: responsibility separation, progressive references, strict
claim-evidence boundaries, bounded prose, figure/table manifests, and rendered
PDF QA.

Second pass, from `ccf-paper-writer/references/` and `ccf-humanization/`:

- `prose-quality-guardrails.md` and `humanization-policy.md` became
  `references/prose-rules.md`: the paragraph job list, the banned-pattern
  table, the em-dash and filler limits, claim calibration in both directions,
  and the rule that warning-only concerns never enter a source file.
- `table-style-guide.md` informed `references/table-grammar.md`, but the
  patterns were rewritten from the exemplar's own `NiceTabular` sources rather
  than from the guide's two-column `booktabs` examples, because the target
  format is single-column NeurIPS.
- `length-budget-policy.md` motivated measured word budgets. The budgets
  themselves were counted from the exemplar's section files, not adopted from
  the guide's venue tables.
- `scripts/check_prose_quality.py` motivated a deterministic prose gate. Ours is
  a separate LaTeX-aware implementation: it strips math, floats, and commands
  before counting, treats removed displays as sentence boundaries, exempts
  acknowledgments, and adds a canonical-term check driven by
  `paper/macros.tex`.

Not integrated in the second pass: the 30-plus venue guides, the exemplar PDF
corpus, Codex/MCP reviewer wiring, and the score-lifting loop.

Not integrated: the full routing framework, unrelated idea/rebuttal/project
skills, automatic image-generation preference, and venue-specific house rules.
This repository's agent must remain self-contained.

## ccf-conference-skills

Repository: `SimonZeng7108/ccf-conference-skills`
Commit: `92cf3b5313ad12eb2113fbfb86e2131bbc67673b`
License: no license file found in the reviewed snapshot

All 109 venue `SKILL.md` files were inventoried. They are mostly venue profiles
for templates, anonymity, page limits, references, and camera-ready checks.

Integrated here: only generic venue-compliance discipline and the distinction
between figure captions below and table captions above. The target exemplar is
NeurIPS 2025 single-column, so CVPR-style two-column rules were rejected.

Not integrated: copied venue prose, unverified future-year rules, hard-coded
2026 deadlines/page limits, and the 109-profile catalog. Final venue rules must
be refreshed from official sources.

## autoresearch

Repository: `karpathy/autoresearch`
Commit: `228791fb499afffb54b46200aca536f79142f117`
License: README states MIT

The repository has no `SKILL.md`; `program.md` is the instruction surface.

Integrated here: frozen evaluation, baseline first, fixed comparable run
budget, log redirection, one coherent change per experiment, simplicity as a
selection criterion, and autonomous continuation within an explicit mode.

Changed rather than copied: discarded experiments are preserved and reverted,
not erased with `git reset --hard`; run identity includes split and trajectory
seeds; paper mode has a terminal gate instead of looping forever.

Not integrated: its LLM-specific training files, one-file edit boundary,
five-minute budget, and single val-bpb objective.

## Auto-claude-code-research-in-sleep

Repository: `wanshuiyin/Auto-claude-code-research-in-sleep`
Commit: `94d8093ed21d20a790830318190095b9f5036ce8`
License: MIT

All 82 top-level skill entrypoints were inventoried; mirrored Codex/backend
copies were treated as variants rather than separate capabilities. The useful
paper subset included `paper-plan`, `paper-write`, `paper-figure`,
`paper-compile`, `paper-claim-audit`, `experiment-audit`, `result-to-claim`,
`citation-audit`, and `auto-paper-improvement-loop`.

Integrated here: plan -> figures/tables -> write -> compile -> fresh-context
claim/citation/scientific/visual audits, verified BibTeX, reverse evidence
checks, limited review-fix cycles, and fail-closed submission readiness.

Second pass, from `skills/paper-write/SKILL.md`:

- the five sequential revision passes (clutter, verbs, architecture, keyword
  consistency, numeric and citation integrity) became the corresponding section
  of `references/prose-rules.md`;
- the banana rule, restated there and enforced mechanically through
  `paper/macros.tex` and the prose gate;
- the reverse-outline test, now the closing step of
  `references/section-playbook.md`;
- the bibliography rule that only cited keys are written and no entry is ever
  fabricated;
- the compile-measure-expand loop, which here compares against measured word
  budgets rather than a page count guess.

Not integrated in the second pass: the fixed reviewer model constant, the
venue-constant block, theory-paper proof inlining, and the poster/slides/talk
adapters.

Not integrated: hard-coded reviewer models/MCPs, Overleaf/notification/cloud
services, patent/poster/slides workflows, hash-heavy assurance machinery, and
large duplicated instruction surfaces.

## Layout exemplar

Paper: arXiv:2506.21656v3, *Fine-Grained Preference Optimization Improves
Spatial Reasoning in VLMs*
Inspected: all 25 PDF pages, plus the complete arXiv e-print source, including
`neurips_2025.tex`, every section file, every table and figure wrapper, and the
official `neurips_2025.sty`.

Measured from the source and encoded as a contract:

| Quantity | Exemplar |
|---|---:|
| Abstract | 154 words |
| Introduction | 495 words |
| Related Work | 503 words |
| Method | 1724 words, 10 numbered equations |
| Experiments | 688 words |
| Conclusion | 224 words |
| Main body | 3634 words |
| Appendix | 3376 words, 7 lettered sections |
| Main-body `\cite` calls | 70 |
| Bibliography entries | 153 |
| Page roles | 1-10 main, 11-17 references, 18-25 appendix |

Also taken as grammar, not content: the title-block `tabular` proportions, the
uncaptioned page-1 teaser, `\toprule[1.2pt]` with `\midrule[1.2pt]\midrule`,
`NiceTabular[colortbl-like]` with family row tints, the caption-legend swatch,
`\resizebox` as the width fix, the paired 0.48/0.44 minipage ablation float,
the narration sandwich around every display, the bold-lead caption, the
labeled-principle device, and the lettered appendix roles.

Both deterministic gates were calibrated against this source: it passes
`check_paper_structure.py` and `check_prose_quality.py` with zero errors, which
is the evidence that the gates are strict but not stricter than a real accepted
paper in this format.

Not copied: prose, claims, figures, logos, icons, examples, model or method
names, dataset semantics, or task-specific technical content.
