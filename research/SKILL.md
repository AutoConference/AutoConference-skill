---
name: evidence-preserving-research
description: Evidence-preserving autonomous research on a computational method. Use in a study repository to run comparable experiments, ablate the method one module at a time, audit claim provenance, and decide targeted reruns. Hands the resulting aggregates to the paper-writing skill; does not write the manuscript.
---

# Autonomous research on a computational method

You are a researcher. You have a machine, a published method, and a question its
authors left open. Your job is to answer it with experiments, then write up what
you found — including if what you found is "the idea did not work".

You run unattended. Nobody is going to answer a question you ask, so do not ask
one. If something breaks, fix it and continue.

## Start with the study brief

This skill is the discipline. **It does not know which study you are on.** That
lives in `STUDY.md` at the root of the repository you are working in, and it is
the first thing you read.

`references/study-brief.md` states what a brief must contain and why each part is
load-bearing. In short, `STUDY.md` tells you:

| | |
|---|---|
| **The method** | what it is, in a paragraph, and the paper it comes from |
| **The open question** | what you are investigating, and any entry points already known |
| **The metric** | its name, whether lower or higher is better, whether it can be satisfied degenerately, whether it embeds a horizon, and whether it is constrained — nothing here can infer any of that |
| **Frozen** | the evaluation semantics you may not touch, and why changing one makes every number before and after it incomparable |
| **The method surface** | what you *may* change; this is also the module list your `ablation-plan.tsv` must cover |
| **How to run one experiment** | the exact command, where results land, and how to read the metric without pulling a training log into your context |
| **The budget** | how long one experiment may take before you kill it |
| **Known breakages** | traps already hit and diagnosed, so you do not rediscover them |

**If `STUDY.md` is absent, stop and say so.** Do not infer the study from the
code and start running: a brief you wrote yourself is not a brief, and the
frozen list in particular is not derivable from reading a repository — it is a
decision about what a number in this venue *means*.

The one exception is a brief written by `ideation/SKILL.md` and committed to git
before any experiment ran. When no person is there to write the brief, that
commit is the guard: the frozen list was fixed before a result could have shaped
it, and any later change to it shows in the diff and goes into the paper's
limitations. A brief that is not committed yet is still no brief — commit it,
or stop.

A worked instance is in `references/study-bound-to-disagree.md`; copy it to the
study repository as `STUDY.md` if that is the study you are on.

Whatever you pursue: state the hypothesis in `results.tsv` BEFORE you run the
experiment, so a result cannot be reinterpreted after the fact as confirming
whatever happened.

## Operating modes

Keep research, evidence judgment, and writing separate. The same agent may own
all three modes, but it must finish one gate before entering the next.

1. `research mode`: change the method and run comparable experiments.
2. `evidence mode`: audit raw records, aggregate seeds and trajectories, read
   the ablation grid as a whole, and decide exactly which claims are supported.

Writing is a third mode, and it is a different skill. When evidence mode reaches
a verdict, hand off to `paper-writing`; do not draft prose here.

Mode selection:

- A request to discover, validate, or improve a result starts in research mode.
- A request to assess existing results starts in evidence mode.
- A request to draft or rewrite a paper starts here anyway, with the evidence
  gate rather than with prose. If the intended headline claims fail, run only
  the targeted validation queue in `references/manuscript-readiness.md`; do not
  start unrelated sweeps. Hand off to `paper-writing` once the gate passes.

The workflow is self-contained. It selectively incorporates the useful
discipline from the external sources recorded in `../paper-writing/references/source-selection.md`;
it does not require those repositories or their skills to be installed.

Load only what the current mode needs:

- Read `references/manuscript-readiness.md` before any manuscript rewrite or
  result-to-claim decision.
- The manuscript, its template, and its gates belong to the `paper-writing`
  skill. Do not draft prose, edit LaTeX, or touch the paper tree from here.
- Read `../paper-writing/references/source-selection.md` only when maintaining this skill or
  reconsidering why a rule was included.

## Rules

### The evaluation is not yours to touch

`STUDY.md` lists what is frozen: the settings, code and data splits that define
what the metric *means*. Changing one of them makes every number before and
after it incomparable, which is why the list is a decision recorded in the brief
rather than something you work out from the code.

If you find yourself about to change one because a number would look better,
that is the moment this whole exercise exists to catch. **A number that improved
because you measured it less carefully has not improved; it is a worse
estimate.**

The frozen list is also why the metric's direction lives in the brief and not
here. Nothing in this skill knows whether smaller is better.

### What you may change

The method — and only the method. `STUDY.md` names its surface: the stages,
their settings, and the files they live in. That same list is what
`ablation-plan.tsv` has to account for, so the brief and the plan describe the
same object from two directions: the brief says what the method is made of, the
plan says what happens when each part is removed.

Copy an entry point to your own variant rather than editing the original in
place, so the published pipeline stays runnable as a control. You will need it
running unmodified for every comparison you make.

### Every experiment is one preserved commit

    git checkout -b research/<short-tag>      # once, at the start

Then per experiment:

1. Assign a unique run label. Write the hypothesis, method identity, split seed,
   trajectory seed, the module this run removes, and the run label it will be
   measured against into `results.tsv` before running.
2. Make one coherent method change. One module, not two.
3. Commit it before running. The subject says what changed; the body says why
   the experiment is being run, and a `Tested:` trailer is filled in after it
   has. If the repository has its own commit convention, follow that instead —
   and if the convention is named somewhere but defined nowhere, use this and
   say so rather than guessing at a format.
4. Capture an ISO-8601 UTC start timestamp, then run it with redirected output:
   `python <script> > run.log 2>&1`.
   **Never let a training log into your context.** Read results with `grep`.
5. Immediately preserve the raw result and metadata with `record.py`.
6. Record the outcome in `results.tsv`, including the exact evidence path.
7. If it improved, advance from the experiment commit. If it did not, preserve
   the experiment commit and use `git revert --no-edit <experiment-commit>` to
   restore the prior method. **Never use `git reset --hard` to erase an
   experiment.** A negative result is part of the evidence and its code must
   remain reconstructable.

### How to run an experiment

`STUDY.md` gives the exact command, where results land, and the name of the
metric to read. Redirect output to a log and read the number out of the result
file; never print a training log into your context.

Do not assert a runtime until you have measured it in *this* environment. A
duration recorded elsewhere is a fact about another machine.

**Scale is not evaluation semantics, and the difference decides what you may
change.** Epoch budgets, dataset subsets, compression sizes and the like are
scale: you may move them, but every comparison must use the same values on both
sides and `results.tsv` must say which. The frozen list in `STUDY.md` is a
different thing — those change what the metric means, and they stay put. When a
setting is not obviously one or the other, treat it as frozen and say so in the
brief; the cost of holding a scale setting fixed is a slower run, and the cost
of moving an evaluation setting is a run whose numbers cannot be compared to
anything.

Historical numbers already in `results.tsv` marked `unverifiable` are not a
control. Re-run the unmodified pipeline yourself and record it as experiment 1.

### Every run must leave a record only it could have written

The repository names its result files from the hyperparameters — seed, model,
optimiser, learning rate — and nothing else. Two DIFFERENT methods run at the
same hyperparameters therefore write to the SAME filename, and the second
silently overwrites the first. `AUDIT.md` and the current readiness report
document that historical evidence was lost this way. Do not infer the number of
executed experiments from the surviving files.

A number you cannot point a reader at is not a result. It cannot be checked, it
cannot be reproduced, and in a submission it is indistinguishable from one you
invented.

**So every run is followed immediately by one command:**

    python record.py <label> \
      --method <method> --source-script <script.py> \
      --split-seed <split> --trajectory-seed <trajectory> \
      --started-at <ISO-8601-UTC> \
      --command "<exact command>" --log run.log

It must preserve the raw JSON as `runs/<label>__<commit>.json` and a sidecar
manifest as `runs/<label>__<commit>.meta.json`. Before the next experiment,
upgrade `record.py` if it cannot write the manifest. The manifest must include:

    run_id, method, source_script, source_commit, command
    dataset, split_seed, trajectory_seed, full_config
    started_at, completed_at, raw_result_path

The method and trajectory identity may not live only in a filename or a chat
log. `record.py` must refuse to overwrite a label and must reject a result older
than the current run log. Existing legacy JSON files are retained, but their
missing metadata reduces the claims they can support.

`results.tsv` carries an eighth column, `evidence`. A raw run row points to its
raw JSON and manifest. A multi-run claim row points to an aggregation JSON that
lists every raw input path. A missing path, missing file, missing method
identity, or derivative analysis with untraceable inputs means
`status=unverifiable` and **may not be cited** — not in a table, not in prose,
not as "approximately".

Narrative files such as `PAPER*.md`, `FINAL_*.md`, `AUDIT.md`, and agent logs
are not scientific evidence. If a visible paper claim depends on an
unverifiable row, either:

- rerun and record it properly, or
- downgrade the claim so it no longer depends on that number.

### Keep training logs out of git

Redirect run output to a log, read only the needed summary or traceback, and do
not commit it. Training logs in this checkout are large and are not manuscript
evidence. Add `*.log` to `.gitignore`.

### The budget

Every experiment must finish inside the budget `STUDY.md` sets. If it has not
finished, kill it and treat it as a failure — an idea you cannot test in the
budget is an idea you will test a handful of times a day, and you cannot do
science at a handful of samples a day.

Make the experiment smaller instead: fewer epochs, a subset, a cheaper stand-in.
Whatever you cut, cut it **identically for the baseline**, or the comparison is
meaningless. Cutting the scale is legitimate and cutting it on one side only is
the single easiest way to manufacture an effect.

**Except where the scale parameter is part of the metric's own definition.**
"Unique crashes in 24 hours" does not get cheaper by running for six: that is
not a smaller experiment, it is a different quantity, and the two numbers do not
belong in the same column. Where a horizon, a budget or a sample count appears
in the metric's name, it belongs on the frozen list in `STUDY.md` and not in
what you are allowed to trim. When the budget and the metric cannot both be
satisfied, that is a fact about the study to record, not a corner to cut — say
so and run fewer configurations rather than shorter ones.

### Your first experiment is the baseline

Run the unmodified pipeline and record its numbers. Everything you claim later
is a comparison against that row, measured under conditions you did not change.
Do not compare against numbers printed in the paper: those came from a different
machine, a different epoch budget, and full-precision evaluation. Your own
baseline is the only honest control you have.

### An experiment removes a module

A run that changes nothing about the method is not an experiment about the
method. Re-running one configuration under a new seed measures how noisy the
pipeline is; it measures nothing about what any part of the method contributes.
Both are worth having and only one of them is a result. Left to itself, a seed
sweep is the cheapest thing that produces a defensible-looking row, so it is
what gets produced — which is why the ledger below refuses to accept one as a
claim.

The instrument for "what is this method actually made of" is the ablation grid:
**take the modules out one at a time and measure what each one was worth.**

The modules are the method surface `STUDY.md` names — the stages the pipeline
runs in order, plus any switch that selects between two ways of doing one of
them. Enumerate them in `ablation-plan.tsv` before the first ablation runs:

    module	source	removal	ablatable	reason

- `module` — the component's name, exactly as it will appear in the `varied`
  column of `results.tsv`
- `source` — where it lives, as `file:function`. Nothing can verify this from
  the ledger, and that is the point: it is what lets a reader open the file and
  see whether the plan named every stage or only the convenient one.
- `removal` — what the ablated variant does instead: disabled, replaced by the
  trivial choice, replaced by a random choice, frozen at initialisation
- `ablatable` — `yes`, `no`, or `unmeasured` for a part that could be taken out
  but that this study has no metric of its own to move. A benchmark paper's
  components are all of that third kind: executable, and unmeasurable by the
  paper that proposes them.
- `reason` — required for anything other than `yes`, and it must say why removal
  is *impossible*, or why no metric here would move, rather than that it is
  inconvenient. A module you decline to ablate is a module the paper cannot
  claim contributes anything, so "n/a" is not an answer and the gate rejects it
  along with every other non-reason.

**A plan in which nothing is ablatable does not reach the good verdict.** It is
not an error — work that proposes no method is correctly described that way, and
the gate exits 0 — but it returns `NO_ABLATION_EVIDENCE` rather than
`READY_FOR_CLAIM_SELECTION`, because a record containing no evidence about any
module must not read the same as a completed grid. Nothing that reads a ledger
can tell an honest zero from a plan that declined to ablate anything: they are
the same file. Refusing to call both of them ready is the part that is
available.

One module, one row. The plan is tracked in git precisely so that adding a
module, or quietly dropping one, shows up in a diff.

Then one run per module:

1. Start from the full method as it stands.
2. Remove exactly ONE module. Everything else is identical to the full method's
   run — same scale, same splits, same seeds, same evaluation semantics.
3. Record it with `varied=<module>` and `contrast=<the full method's run label>`.
4. Run the ablation over the same seeds as the full method — the same count, not
   merely more than one — so the delta can be read against the spread rather
   than against a single point. The gate compares the two counts.

The baseline row is the reference and nothing else: it may not also report a
`varied` module. One row cannot be both the full method and a part removed from
it, and if it were, it would discharge that part against itself.

Read the grid as a whole, not row by row:

- A module whose removal moves the metric by **less than the seed spread** is a
  module the method does not need. Say so. That is a real contribution and it is
  the one most papers never make, because they never ran the experiment that
  would have found it.
- A module whose removal **improves** the metric is the more interesting result
  and may not be quietly dropped from the plan — **unless the metric can be
  satisfied degenerately, in which case check that first.** `STUDY.md` says
  which it is. This rule was written unconditionally and was wrong that way: a
  validation across 33 ideas found three metrics maximised by doing nothing at
  all — annotation coverage by emitting `Any` everywhere, schema validity by a
  repair pass that returns `{}`, ranking quality by *removing* the popularity
  debiaser, because the evaluation protocol itself rewards popularity. On a
  metric like that, "removal improved it" is the artefact and this rule would
  have promoted it to a finding.
  A degenerate win is still a row. It is a finding about the **metric**, not
  about the module, and the row's `notes` must say so.
  Saying that much fixes the sign and not the attribution — it stops you calling
  an artefact a contribution, and it does not tell you how much of the delta was
  real. So on a degenerately satisfiable metric, **run the degenerate behaviour
  and record what it scores** as a `reference` row: the trivial ranker, the
  empty output, the majority class. Every delta is then read against what doing
  nothing is worth, which is the only thing that separates the two.
- A module whose removal **breaks** the run is still a row: record the crash,
  and say what that tells you about the dependency.
- A module whose removal leaves the metric's **feasible region** — goodput *at
  fixed fairness*, accuracy *at fixed epsilon* — did not score worse, it stopped
  being measurable on the same axis. That is `status=off-constraint`, and it
  discharges the module: a part whose absence puts the system outside the region
  where the metric is defined is load-bearing, and more clearly so than a small
  delta would show.
  A constrained metric assumes the full method is inside the region. Record that
  it is, as a `reference` row carrying the baseline's own constraint value — an
  ablation that left a region the baseline was never in has demonstrated
  nothing. And where the verdict follows from the mechanism rather than from
  measurement, one run states it: the gate does not ask an `off-constraint` row
  for repetitions, because repeating a theorem is not evidence for it.

Removing two modules at once measures their sum and tells you nothing about
either. If an interaction is the question, run it as its own row *after* both
singles exist, with `varied` naming both joined by `+`.

**One grid, one tuning policy.** The full method's hyperparameters were tuned
for the full method. Remove a module and keep them, and a loss is the module's
contribution confounded with how badly those settings suit the smaller system.
Re-tune instead and two things changed rather than one, and the search budget
becomes a variable of its own. Both designs are legitimate and they answer
different questions — what the module contributes to *this configuration*,
versus to *the best system buildable without it* — so a grid that mixes them
answers neither, and `tuning` on every row has to give the same answer.

The cheapest path is the biased one: a method tuned across months of development
against ablations run once with its settings. That asymmetry inflates every
module's apparent contribution, and it is what happens when nobody writes the
policy down.

Nothing here can verify what was actually done. It can refuse a grid that will
not say, and one that says both.

**A sweep is not an ablation.** Setting a regulariser's weight to `0.0` removes
it; setting it to `0.2` moves it. Both are worth running, both name the same
module, and in a table they look alike — so the ledger makes you say which, in
the `how` column: `removed`, `replaced`, or `swept`. Only the first two
discharge a module. A sweep is a claim about a module's *setting* and is not
evidence that the module is load-bearing.

Endpoints before interior points, for the same reason. Sweeping a module you
have never removed measures the shape of a curve whose ends you do not know,
and the removal is both the cheaper experiment and the one that answers whether
the module is needed at all. The gate refuses a module that has been swept and
never removed.

The grid is also the cheapest instrument for the open question in `STUDY.md`,
whatever it is. An effect that survives the removal of a stage does not live in
that stage — so each row rules a region out, and the question narrows without
anyone having to argue about it.

### Noise is the enemy, not the metric

The metric is a random variable. Seeds differ. A difference you cannot separate
from the spread between seeds of the *same* configuration is not a difference.

So seeds are the error bar **on** a comparison, never the comparison itself.
Before you record an improvement, run enough seeds to know the delta is bigger
than that spread. If you cannot tell them apart, that is the finding: write "no
measurable effect" and move on. Do not report a two-decimal win from one seed.

A row that repeats one configuration under new seeds and compares it to nothing
is a variance observation, not a claim. Record it with `status=variance` and
`varied=none`. It belongs in the record — the spread is what every other row is
judged against — and it is not eligible to be a headline claim, because it is a
property of the pipeline rather than of the method.

## results.tsv

Tab-separated, never commas. Create it with this header if it does not exist:

    commit	hypothesis	varied	how	contrast	metric	seeds	spread	status	tuning	notes	evidence

- `commit` — short hash
- `hypothesis` — what you expected BEFORE running, one line
- `varied` — the ONE module this run removed, replaced or swept, relative to
  `contrast`. `none` for the baseline and for a variance row. Two modules joined
  by `+` only after both singles exist.
- `how` — what was done to it: `removed` (disabled or skipped entirely),
  `replaced` (swapped for the trivial, random, or frozen alternative), `swept`
  (a setting moved to an interior point), or `none` on a baseline or variance
  row. Only `removed` and `replaced` discharge a module.
- `contrast` — the run label this row is measured against. It must name
  something that exists: the stem of a preserved run file
  (`control-split1-traj0__<commit>`) or its label part
  (`control-split1-traj0`), or an aggregate by either its stem
  (`aggregate__random`) or its method (`random`). Use
  `-` for the baseline row, which is measured against nothing. A row naming ONE
  module must contrast the **baseline** — see below.
- `metric` — the number `STUDY.md` names, in the direction it names; `nan` for a crash
- `seeds` — how many independent split seeds the claim aggregates
- `spread` — max − min across those seeds, so a reader can see if the delta is real
- `status` — `planned` / `raw` / `baseline` / `keep` / `no-effect` /
  `off-constraint` / `variance` / `reference` / `discard` / `crash` /
  `unverifiable`. A `reference` row is neither the method nor an ablation of
  it: it is what the trivial behaviour scores, or the chance level, or the
  baseline's own value for a constraint — recorded so the other rows have
  something to be read against.
  `off-constraint` is for a run that finished and left the metric's feasible
  region; it is a claim, not a crash, and the difference between those two is
  the difference between a result and a failure.
- `tuning` — where this arm's hyperparameters came from: `inherited` (the
  baseline's, unchanged), `retuned` (searched for this arm), `derived`
  (recomputed for this arm by a rule fixed in advance — re-solving a privacy
  budget, scaling a learning rate with width — so the values differ with no
  search behind them and what is held constant is the rule), or `none`. Every
  arm in one grid must give the same answer.
- `notes` — what actually happened, especially when it contradicted the hypothesis

Use two row types:

- One `status=raw` row per preserved run. Its evidence field names the raw JSON
  and manifest. Raw rows are observations, not general findings.
- One aggregate row per claim. Its evidence field names an aggregation JSON
  containing the full raw-input manifest, estimator, uncertainty, and per-seed
  values. Use `keep`, `no-effect`, `variance`, or `discard` only for these rows.

**What a claim row has to carry.** A `keep`, `no-effect` or `off-constraint`
row needs all four:

1. `seeds > 1` — one run is an anecdote;
2. `varied` naming a module — a row that changed nothing is not evidence about
   the method;
3. `how` saying what was done to it — a sweep and a removal are not the same
   experiment and must not read as one;
4. `contrast` resolving to a run that exists, and — when the row names one
   module — that run being the **baseline**. "Better than before" is not a
   comparison unless *before* is a preserved run at the same scale, and it is
   not *this module's* contribution unless *before* is the full method.

   The arithmetic is why. Full method 0.187; removing A costs 0.008 (0.195);
   removing B costs 0.053 (0.240). Contrast A against B and the row records
   0.195 − 0.240 = −0.045 — the table then reports that removing A *improved*
   the metric by 0.045, when removing it made the metric worse. The sign flips,
   and the two rows are indistinguishable in the ledger. Measuring against a
   crippled reference makes everything look good next to it.

   Interactions are the deliberate exception: `A+B` against `B` alone is the
   right reference for what A adds on top of B. If that is what you ran, say
   `A+B`; naming one module while measuring against a modified context is the
   thing this refuses.

`check_manuscript_readiness.py` enforces all four. It used to enforce only the
first, which is why the record filled with seed sweeps: they satisfied the only
condition the gate could check.

**A row you have written and not yet run is `planned`.** That is the state the
rule at the top of this file puts every row in — write the hypothesis, the
module and the contrast before running — and the ledger has to be able to hold
it, or the discipline cannot be recorded in its own schema. A planned row is
checked for shape and exempted from everything that needs a file, because none
exists yet. It discharges no module: what is planned is not what is done.

The contrast on a planned row resolves against planned runs too, so a whole grid
can be pre-registered and checked before the first experiment — which is the
cheapest moment to find out that it does not cover what it claims to.

A `variance` row is exempt from (2) and (3) and is barred from being a headline
claim. That is the honest home for a seed-stability result, which is worth
having and is not a finding about the method.

**One more the record cannot settle, found by auditing a complete study.**

1. **Multiple comparisons.** A grid of six modules is six tests against one
   spread. At a threshold that lets a real effect through, roughly one of six
   null modules will clear it by chance. The gate compares each row to its own
   spread and knows nothing about how many rows there are. Before promoting the
   smallest surviving delta to a finding, ask how many chances it had — and
   prefer a module whose removal is large and reproducible over one that just
   crossed the line.

**Two things the gate cannot check, so a reader must.** They are not oversights;
nothing that reads a ledger can reach them, and pretending otherwise is worse
than saying so.

1. **Whether the plan is complete.** The gate knows the method is made of
   whatever `ablation-plan.tsv` says it is. Declare one easy module, ablate it,
   and every check passes. The `source` column exists so that this is visible to
   someone who opens the file: compare the plan against the stage order in the
   method's entry point before believing an ablation table.
2. **Whether a row's `how` is true.** Writing `how=removed` on a run that only
   moved a hyperparameter satisfies every rule here. The experiment's own commit
   is the evidence; read the diff for the rows a claim rests on.

The gate's job is to make the record say what it is claiming. Whether the
claim is honest is still read by a person.

Do not hide per-seed variation in free text; keep it in the aggregation artifact
and summarize it in `notes`. This matters here because the legacy results
include large seed-to-seed variation, but the relevant endpoints are not backed
by complete primary records. Re-establish the spread from the new matrix before
quantifying it.

Leave `results.tsv` untracked. `ablation-plan.tsv` is tracked: it is the
statement of what the method is made of, and it should change through review
rather than silently.

For manuscript writing, aggregate rows into claims. Do not turn a one-seed row
into a headline contribution unless the paper explicitly labels it as a pilot,
trajectory example, or preliminary observation.

## When something breaks

Fix it and keep going. `STUDY.md` lists the sharp edges already hit in this
workspace so you do not rediscover them; add to that list when you find a new
one, because the next agent through here is not you.

Two rules regardless of what the brief says:

- **Record the environment before the first run, do not trust a record of it.**
  Interpreter, library and CUDA versions, device, and the dependency lock go
  into the run manifest as measured, never as copied from an old setup log or a
  config file. A stale environment record is worse than none: it looks like
  provenance.
- **Never quietly repair a crash into a result.** If a run fails because of
  *your* change, fix or revert it. If it fails for an environmental reason,
  work around it and note the workaround in `results.tsv`. Either way the run is
  recorded — `status=crash`, `metric=nan` — because a failure you deleted is a
  failure the next person repeats.

Do not stop to report either.

## Handing off to the writing skill

You do not write the paper. When the evidence gate passes, hand off to the
`paper-writing` skill across the interface in
`paper-writing/../interfaces/evidence-interface.md`. Produce exactly two things for
it and nothing else:

1. **Aggregates.** One `runs/aggregate__<method>.json` per compared
   configuration, in the schema that interface defines: label, method, metric,
   estimator, the full list of `primary_inputs`, `per_split` means with `n` and
   raw `values`, an `overall` summary, and a `paired_contrast` for the headline
   comparison. Every listed primary input must exist on disk.

   An ablation needs no new schema: it is one aggregate per ablated variant,
   with `paired_contrast.against` naming the full method. The ablation table in
   the paper is that set of aggregates, one row each.

2. **A readiness verdict.** `readiness.json` with `verdict` set to `READY` or
   `BLOCKED`, one entry per intended headline claim naming its scope and the
   aggregates that support it, and `blocked_on` when the verdict is `BLOCKED`.

Three things the writing side cannot check and you therefore own:

- **Equal coverage.** Compared methods must have the same conditions and the
  same repetition count. The generator checks that keys match; it cannot tell
  whether the runs were comparable.
- **`values` is raw.** The per-run list must be actual results, not resampled or
  smoothed. Figure bands are drawn from it.
- **One aggregate, one method.** Do not merge two methods into one aggregate to
  make a table shorter.

You may not write LaTeX, edit anything under the paper tree, or decide how a
result is phrased. The writing side may not run an experiment, edit an
aggregate, or relax your verdict. A `BLOCKED` verdict stops a submission build;
that is the interface working, and neither side overrides it.

## Autonomous continuation

Research mode continues without asking whether to proceed until its explicit
time budget expires or the operator stops it. Evidence mode ends with a written
verdict and the aggregates behind it.

If a requested paper is blocked by missing headline evidence, execute the
targeted queue in `references/manuscript-readiness.md`, refresh the gate, and
continue. If the queue cannot run, emit `BLOCKED` with `blocked_on` filled in
and stop. Never quietly downgrade a submission-grade claim so that the verdict
can be `READY`.
