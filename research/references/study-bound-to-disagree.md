# STUDY.md — Bound to Disagree (P2L)

The study brief for `evidence-preserving-research`. Copy this file to the root
of the study repository as `STUDY.md`; the skill reads it there, not here.

It is kept in the skill as the worked instance of
[`study-brief.md`](study-brief.md) — every section below answers one of that
contract's questions, and the text is the one this skill carried before the
study-specific and the general parts were separated.

**The metric is `p2l_bound`, and lower is better.** Nothing in the skill can
infer that; every reading of an ablation delta depends on it.

## The work you are building on

`Bound to Disagree: Generalization Bounds via Certifiable Surrogates`
(Bazinet, Zantedeschi & Germain, UAI 2026) — this repository is the authors' own
code. Read `README.md` and the paper's method before your first experiment.

The idea: you cannot compute a tight generalization bound for a big neural
network directly, but you *can* for a simpler surrogate. So bound the
**disagreement** between the target and the surrogate on unlabeled data, and
combine it with the surrogate's own guarantee to certify the target.

## The open question — this is what you are investigating

The local research brief and historical drafts describe an apparent anomaly:
random coreset selection was reported as producing a tighter bound despite
providing less direct control over disagreement. The primary paper PDF is not
stored in this checkout, and OpenReview currently blocks automated retrieval,
so do not reproduce the historical text as a verified quotation. Verify the
paper directly before quoting it in a manuscript.

Treat the anomaly as a research question, not as an established result in this
workspace. The local rows that contain its historical numbers are currently
marked `unverifiable`.

Your job is to find out why, and whether it can be exploited. Some entry points
— you are not restricted to these, and a better question of your own is welcome:

- Is it a variance effect? Optimising disagreement on a finite unlabeled sample
  could overfit that sample, so the certified bound pays for it. If so, the
  effect should depend on unlabeled-set size in a predictable direction, and
  that is testable.
- Is it a KL/complexity effect? Optimising disagreement may push the surrogate
  away from its prior, loosening its own guarantee by more than the tighter
  disagreement term gains.
- Does a partial or regularised objective beat both extremes? "Do not optimise"
  and "optimise fully" are two points on a line nobody has swept.
- Is the anomaly stable across seeds, or is it a small-sample artefact in the
  paper's own numbers?

Whatever you pursue: state the hypothesis in `results.tsv` BEFORE you run the
experiment, so a result cannot be reinterpreted after the fact as confirming
whatever happened.

### The evaluation is not yours to touch

These are fixed. They define what a bound *means* in this venue, and changing
one makes every number before and after it incomparable:

    mc_samples             evaluation precision, fixed for the whole run
    delta                  confidence level
    nbr_parameter_bounds   bound-inversion grid
    the data splits        train / validation / disagreement / test
    bounds/*.py            the bound computations themselves
    baseline_logs/         the target models everything is certified against

If you find yourself about to change one because a number would look better,
that is the moment this whole exercise exists to catch. A bound that got tighter
because you sampled less is not a tighter bound; it is a worse estimate.

**You may not edit `bounds/`, `configs/dataset_configs/`, `baseline_logs/`, or
anything under `DeepCore/`, `PBB/`, `Pactl/`.**

### What you may change

The method. Surrogate construction, how (and whether) disagreement is optimised,
training schedule, regularisation, the objective. This lives in `main_p2l.py`,
`utilities/`, and `models/`. Copy a `main_*.py` to your own variant rather than
editing a paper entry point in place, so the paper's own pipeline stays runnable
as a control.

### How to run an experiment

The experiment bed is the **P2L line on MNIST**, entered through `probe_one.py`:

    CUDA_VISIBLE_DEVICES=0 python probe_one.py -d mnist --index 0 \
        --max-epochs 12 --max-compression 120 > run.log 2>&1

This is the legacy reduced-scale probe command. Its runtime is machine- and
environment-dependent and must be measured again. Results land in
`experiment_logs/*.json`. Read the metric from the JSON rather than printing a
full training log.

The primary metric is `p2l_bound` (and `full_disagreement_bound_p2l` for the
disagreement variant). The historical baseline numbers in `results.tsv` are
marked `unverifiable`; do not repeat them here or use them as a control. Re-run
and record the unmodified pipeline as experiment 1.

`--max-epochs` and `--max-compression` are experiment SCALE. You may change them,
but if you do, every comparison you make must use the same values on both sides,
and you must say so in `results.tsv`. The repository configs set the original
MNIST scale to 200 epochs and a maximum compression size of 20,000; the legacy
probe uses 12 and 120. Do not assert a runtime until it is measured in the new
environment. These are scale settings, whereas `delta`,
`nbr_parameter_bounds`, and the bound code are evaluation semantics and remain
off limits.

**The PAC-Bayes line (`main_pbb.py`) is broken in the authors' release** —
`compute_pac_bayes_disagreement` returns three scalars while
`compute_pac_bayes_disagreement_bound` indexes them as lists, so it raises
`TypeError: object of type 'numpy.float64' has no len()`. Do not try to fix it
and do not build on it; it is a finding to report, not a task. Use the P2L line.

## The budget

Each experiment must finish in **under 15 minutes**. That number is a property
of this study's reduced-scale probe, not of the discipline: an idea you cannot
test in fifteen minutes is one you will test four times a day, and you cannot do
science at four samples a day.

## When something breaks

Fix it and keep going. Known sharp edges in this repository, already hit and
diagnosed, so you do not have to rediscover them:

- Requirements are split across files under `requirements/`; do not assume the
  imported `btd` environment still matches any one of them. Run and record an
  environment preflight before experiments.
- Environment records in this workspace disagree about Python, PyTorch, and
  CUDA versions. Before any rerun, record the actual interpreter, PyTorch/CUDA
  versions, GPU model, and dependency lock in the run manifest. Do not copy the
  versions claimed by `paper.json` or an old setup log into the manuscript.
- Datasets are loaded with `download=False`. MNIST and CIFAR10 are already
  present. Do not add new datasets that need downloading.
- `wandb` runs offline (`WANDB_MODE=offline`). Do not try to log in.
- The disagreement bound needs target models from `baseline_logs/` — one per
  seed in `[1,2,3,4,42]`. Five JSONs exist; their stored validation errors range
  from approximately 0.0080 to 0.0108. If
  `get_best_model` raises `UnboundLocalError` about `config_list`, that means it
  found no baseline logs, not that the code is broken.
- The imported setup log records CUDA availability and two visible GPUs but
  does not identify both models. Do not claim they are two RTX 4090s. Select a
  device only after the new environment preflight and record that choice.
- `configs/experiment_configs/baseline/mnist.yaml` currently lacks
  `lr_scheduler`, while `utilities/utils_models.py` reads that key directly.
  Resolve this explicitly before a baseline run (the local
  `fix_baseline_cfg.py` proposes `None`) and record the resulting config; do not
  claim the fix is applied until the YAML actually contains it.

If a run crashes for a reason that is *your* change, fix or revert it. If it
crashes for an environmental reason, work around it and note the workaround in
`results.tsv`. Do not stop to report either.
