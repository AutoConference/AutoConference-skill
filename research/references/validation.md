# Validation: 33 ideas across computer science

Dated 2026-09-02, against the skill at commit `6c73a8d`.

The gate had been checked only against fixtures written by the person who wrote
the gate. That proves the code does what its author meant and nothing about
whether the discipline survives contact with research it was not designed
around. So: 33 method proposals spanning fourteen areas of computer science,
each given to an agent that had the skill and nothing else, with instructions to
produce `ablation-plan.tsv` and the pre-registered rows — and no hint about what
a good answer looks like.

Each idea supplied only what a study brief supplies: the method in a paragraph,
the metric, and its direction. **The module decomposition was never given** —
working it out is the thing under test.

## What was covered

ML (curriculum pretraining, mixture-of-experts, contrastive learning,
sharpness-aware training) · NLP (RAG, chain-of-thought distillation, byte-level
LM, constrained decoding) · CV (tracking with memory, diffusion sampling,
open-vocabulary detection) · RL (offline, model-based) · speech (streaming ASR) ·
systems (inference scheduler, gradient compression, serverless cold starts) ·
databases (learned index, learned cardinality estimation) · compilers
(superoptimisation, gradual type inference) · networking (learned congestion
control) · security (malware CFGs, fuzzing, DP fine-tuning) · IR (sequential
recommendation) · graphics (NeRF) · robotics (action chunking) · SE (program
repair, flaky test detection).

Three were included because the frame was expected to break: a **new activation
function** (one component), a **benchmark paper** (no method at all), and a
**prompting technique** (no code).

## What held

```
33 ideas · 192 modules declared · 159 ablatable · 159 discharged by a
removal or replacement row
missing baseline rows: 0    invalid `how` values: 0    uncovered modules: 0
```

Every ablatable module in every plan had a corresponding removal row. Across
fourteen fields, nobody produced a seed sweep and called it an ablation, and
nobody left a declared module undischarged.

`ablatable=no` was used correctly and unprompted for the recurring case of a
component that is the *measurement* rather than the method — the linear probe in
contrastive learning, the generator in RAG, the equivalence verifier in
superoptimisation, crash deduplication in fuzzing. That distinction was never
spelled out to them.

**All 33 reported that no `STUDY.md` existed and that the skill says to stop.**
The precondition fired in every field.

## The measurement was wrong twice, and how

Recorded because the corrections are the finding.

**26 "hyperparameters disguised as modules" were a false alarm.** The real count
is zero. Most flagged cells read like this:

    load_balancing_aux_loss   removed: auxiliary coefficient set to 0.0
    cql_penalty               removed: the conservative penalty weight is set to 0

**A loss weight set to zero is the removal**, expressed the way that
architecture expresses it — not a dial being turned. Only a *non-degenerate*
value is a sweep. One more cell was flagged because `replaced by uniform
sampling over the training set` contains the word "set".

This changes the argument for a controlled `removal` vocabulary but does not
weaken it: the case for it is not that agents cheat — none did — but that free
text cannot distinguish `weight = 0.0` from `weight = 0.2`, and a closed
vocabulary can.

**46 "chained contrasts" were a defect in the gate.** See below.

## Defects found, by strength of evidence

**1. The ledger cannot express a pre-registered row.** `SKILL.md` says twice to
write the hypothesis into `results.tsv` before running. The status vocabulary —
`raw / baseline / keep / discard / crash / no-effect / variance / unverifiable` —
has no value for a row that has been written and not yet run. **All six agents
independently invented `status=planned`**, as did an unrelated agent in an
earlier A/B run. The doctrine's first rule cannot be recorded in the doctrine's
own schema.

**2. An aggregate cannot be referred to by its method name.** Aggregates are
`runs/aggregate__<method>.json`. `run_identifiers()` accepts the full stem
(`aggregate__ce-full`) and the part *before* the separator (`aggregate`) — but
the method name is the part *after* it. `aggregate` is identical for every
aggregate in a run and so identifies nothing. Six ideas wrote the natural thing
and were blocked:

    contrast='ce-full'             -> BLOCKED: names no preserved run
    contrast='aggregate__ce-full'  -> READY

**3. A method with no ablatable parts is indistinguishable from an evasion.**
The benchmark-paper plan declared six components, all `ablatable=no`, each with
a truthful reason, and passed with zero ablations — the same artifact the
`NON_REASONS` check exists to catch. Its own note says so. `ablatable` is also a
two-valued field with no room for "executable but unmeasurable", which is what
every component of that paper is.

## Boundaries of the method, not bugs

These recurred across unrelated fields and are properties of leave-one-out
ablation itself. They belong in the skill as stated limits.

**Removals are not independent.** Removing the pacing schedule nullifies the
difficulty scorer; sharpness-aware training is a chain, not a grid; RAG stages
are each other's inputs; diffusion modules act inside every step so deltas are
not additive; action chunking has no isolated removal because `chunk_len=1` also
kills temporal ensembling. The grid assumes separability and often does not get
it.

**A removal perturbs whatever the metric holds fixed.** Mixture-of-experts
removals change FLOPs, and the metric is loss *at fixed FLOPs*; the
sharpness-aware ablation halves compute; distillation ablations change corpus
size as well as quality; "PSNR at fixed training time" makes "everything else
identical" unachievable in principle. Several agents invented compute-matched or
size-matched companion rows on their own. The skill says nothing about this.

**A constrained metric can be left rather than lost.** Goodput *at fixed
fairness*, accuracy *at fixed epsilon*: an ablated variant can exit the feasible
region instead of scoring worse, and the ledger has no status for "completed but
off-constraint". One plan was forced to record it as `crash` with `metric=nan`.

**`spread` = max − min over seeds is the wrong uncertainty in most fields.** The
dominant variance is across sequences in tracking, across bugs in program
repair, heavy-tailed in fuzzing crash counts, binomial over rollouts in
robotics. One column, many noise structures — and in offline RL the seed spread
routinely exceeds every module's effect, so an honest grid reads as a method
with no parts.

**"A removal that improves the metric is the more interesting result" can
promote an artefact.** The skill says that, and on a gameable metric it is
actively wrong: type-annotation coverage is maximised by emitting `Any`
everywhere; schema-validity is maximised by a repair pass emitting `{}`;
removing popularity debiasing *raises* NDCG because the evaluation protocol
rewards popularity. The rule needs a clause about whether the metric can be
satisfied degenerately.

**The budget rule can change what is measured.** Fuzzing's metric *is* a
24-hour horizon; "make the experiment smaller" would not shrink the experiment,
it would redefine the quantity.

## What this validation may and may not claim

It may claim that the skill's discipline is legible to an agent that has never
seen the study, in fourteen fields, and that the ablation grid is produced
correctly and completely when it is produced at all.

It may **not** claim the decompositions are scientifically right. Every plan was
written against one paragraph, with no code to check it against — which is
exactly the plan-completeness gap the skill assigns to a human reader. Nor may it
claim anything about execution: nothing was run, and the metric numbers do not
exist.

The agents were batched (roughly six ideas each), so there are six independent
readings of the skill rather than 33. A house style formed within a batch would
not be visible here.
