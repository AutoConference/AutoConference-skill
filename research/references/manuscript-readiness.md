# Manuscript readiness and targeted rerun gate

This reference is both a reusable gate and a dated snapshot of the current
workspace. Refresh the counts and verdicts before every paper-mode run.

Start with `python scripts/check_manuscript_readiness.py`. Its non-zero exit is
an evidence blocker, not a software failure. The script inventories provenance;
the claim-specific matrix below still requires scientific judgment.

## Gate semantics

- `READY`: every headline claim has identifiable primary runs, an aggregation
  over the required independent factors, uncertainty, and no unresolved
  contradiction.
- `BOUNDED_ONLY`: the records support a narrower internal report or pilot
  observation, but not the intended submission claim.
- `BLOCKED`: the intended story depends on missing, overwritten, ambiguous, or
  statistically inadequate evidence.
- `NO_ABLATION_EVIDENCE`: the record is internally correct and no module was
  ever ablated. Not a failure — it is the right description of work that
  proposes no method — and not readiness either. Which of the two it is, a
  reader decides by opening `ablation-plan.tsv`; the gate cannot, because an
  honest zero and a declined grid are the same file.

Primary evidence is a raw run plus a manifest that identifies the method,
source commit/script, full command and config, dataset split seed, trajectory
seed, environment, and timestamps. A derived JSON is not primary evidence. It
is valid only if it lists traceable primary inputs and a reproducible estimator.
Files named `PAPER`, `FINAL`, `SUMMARY`, `AUDIT`, and agent conversation logs are
narrative records, not measurements.

A claim about the *method* additionally needs a contrast: the module it removed,
and the preserved run it was measured against. Repetition under new seeds is a
claim about the pipeline's variance and is recorded as `status=variance`; it is
never a headline claim. The gate enforces this, and it did not always — until it
did, a seed sweep was the cheapest row that could pass, so seed sweeps are what
the historical record mostly contains.

## Current snapshot - 2026-08-26

Verdict:

- submission-grade rewrite: `BLOCKED`
- bounded internal/technical-note rewrite: `BOUNDED_ONLY`
- targeted reruns required for the intended headline story: `YES`

Inventory from `results.tsv` and `runs/`:

- 33 result rows: 13 `keep`, 19 `unverifiable`, 1 `crash`.
- 13 files under `runs/`, of which 9 are raw experiment JSONs and 4 are
  derivative analyses.
- Raw preserved runs cover split seeds 3, 4, and 42 only. No primary raw run is
  preserved for split seeds 1 or 2.
- The only preserved before/after pairs are on split seed 4:
  `hybrid 0.1897 -> 0.1400` and `weighted-temp-0.1 0.1897 -> 0.1400`.
- The saved raw JSON config does not encode the method or a separate trajectory
  seed; those identities currently depend on filename and Git history.
- None of the 9 primary JSONs has the new `.meta.json` provenance sidecar.

Blocking evidence defects:

1. The historical random-vs-max-error comparison and the seed-1/2/3 reversal
   rows are `unverifiable`.
2. The claimed random seed-3 rescue has only the retry endpoint preserved; the
   claimed original value is missing.
3. `runs/correlation__abc677e.json` hard-codes final bounds taken from
   unverifiable rows. It cannot support the `r=0.848` headline.
4. `runs/optimal_retry__2eaefc9.json` contains a summary without enumerating
   primary paired inputs. It cannot support a 75% success rate or deployment
   recommendation.
5. Most remaining raw results are single observations. They cannot establish a
   stable method ranking, a universal rescue mechanism, or a retry success rate.
6. The study uses reduced-scale MNIST runs (`max_epochs=12`,
   `max_compression=120`) rather than the original full scale. General claims
   need either broader validation or explicit scope restriction.
7. There is no `ablation-plan.tsv` and no row removes a module. Every recorded
   comparison varies a seed, a trajectory, or the selection rule. Nothing in the
   record says what the surrogate construction, the disagreement objective, the
   schedule, or the regularisation contributes, so no claim that any of them
   matters is currently supported.

## Targeted validation matrix

Freeze the final claims before running. For the most defensible intended story,
test these two claims:

1. Under a fixed data split and method, trajectory randomness materially
   changes the certified bound.
2. Random and max-error selection do not have a stable universal ranking across
   splits and trajectories.

Minimum submission-grade rerun:

- configurations: random selection and max-error selection;
- split seeds: `1, 2, 3, 4, 42`;
- independent trajectory seeds: at least 3 per split/configuration;
- total: 30 primary runs, all under one frozen reduced-scale protocol;
- analysis: per-configuration mean, standard deviation, range, paired
  within-split contrasts, and best-of-k retry curves computed only from the new
  primary manifest.

Note what that matrix is and is not. It varies seeds and one selection rule, so
it can establish how noisy the pipeline is and whether two selection rules are
distinguishable. It cannot say what any *part* of the method contributes,
because it never removes one. On its own it is a variance study.

Required alongside it — the ablation grid:

- declare the modules in `ablation-plan.tsv` before running anything;
- one variant per module, with that module disabled or replaced and nothing else
  touched: surrogate construction, disagreement optimisation, training schedule,
  regularisation, the objective, the coreset selection rule;
- each variant over the same 5 split seeds as the full method, so its delta is
  read against the same spread;
- the full method's run is the `contrast` for every one of them;
- a module that cannot be removed gets a row in the plan and a recorded reason,
  not silence.

The grid is what turns "the method works" into "these parts of it do the work".
It is also the cheapest route to the study's open question: a module whose
removal leaves the anomaly intact is a module the anomaly does not live in.

Before starting, change the run recorder so split seed and trajectory seed are
separate metadata fields and method identity is inside the manifest. Preserve
every run, including crashes and negative outcomes.

Optional claim-dependent additions:

- If hybrid and weighted methods remain headline contributions, give each the
  same 5-split x 3-trajectory treatment (30 additional runs). Otherwise demote
  them to a seed-4 case study or omit them.
- If the title/abstract claims a general phenomenon beyond reduced-scale MNIST,
  add a second dataset or a representative original-scale validation. Otherwise
  state the MNIST/reduced-scale scope in the title, abstract, and limitations.

## Exit criteria

Change the submission verdict to `READY` only when:

- every raw run and aggregation artifact passes provenance checks;
- every headline configuration has the same split and trajectory coverage;
- every module in `ablation-plan.tsv` has either an ablation row or a recorded
  reason it cannot be removed;
- **a reader has compared `ablation-plan.tsv` against the stage order in the
  method's entry point** — the gate cannot tell a complete plan from a plan with
  one convenient module in it, and this is the check that catches that;
- **a reader has opened the experiment commit behind each headline ablation row**
  and confirmed the module was removed rather than retuned;
- every claim row names the module it varied, what was done to it, and a
  preserved run it was measured against — and a row naming one module is
  measured against the baseline, not against another ablation;
- the paper reports distributional statistics rather than selected endpoints;
- correlation/retry analyses are recomputed from the new manifest;
- all text, tables, and figures use only the refreshed supported claims.

Until then, a paper may honestly report the two preserved seed-4 paired case
studies and the evidence-loss failure, but it must not present trajectory rescue,
the `r=0.848` correlation, 75% retry success, or random/max-error rankings as
established general findings.
