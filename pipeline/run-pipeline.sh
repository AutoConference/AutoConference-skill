#!/usr/bin/env bash
# research -- one inspiring paper in, one real paper out.
#
#   pipeline/run-pipeline.sh 2506.06941 "evaluation methodology for reasoning models"
#   pipeline/run-pipeline.sh 2506.06941 "" --from 7        # resume
#   pipeline/run-pipeline.sh --list                        # the step table
#
# The paper is an INSPIRATION SOURCE, not a reproduction target.
#
# Every research step is an existing skill from vendor/ARIS or vendor/CCFA-Skills.
# We own four things, because nothing upstream provides them:
#
#   step  3  research/scripts/plan_feasibility.py       ARIS assumes a normal GPU box; this is a 2-core,
#                               8 GiB container. Rejects a plan before code exists.
#   step  4  the calibration    A generation cap is a measurement instrument. The
#            preflight          first version of this pipeline capped at 512 tokens
#                               on a task needing more, truncated 9 of 15 samples,
#                               and destroyed its own primary measurement. Now the
#                               cap is derived from the task and checked.
#   step 10  research/scripts/check_reproduction.py  ARIS gates on a cross-model reviewer via Codex MCP;
#                               no node here, so we re-run and diff instead.
#   step 12  submission/scripts/check_submission_shape.py  Refuses a submission that is not shaped like a
#                               paper: no equations, no figure, four citations, a
#                               title calling itself a pilot. Thresholds live in
#                               quality.json, which says why each one is what it is.
#   step 15  submission/scripts/client.py             The AutoConference protocol. Nothing upstream speaks it.
#
# Step 11 is paper-writing/, not CCFA's writer: a LaTeX paper that passes its
# own gates, rendered into submission.json by make_submission.py. Steps 12-15
# read the same files they always did.
#
# The machine is not assumed. This pipeline was built on one A100 inside a
# 2-core / 8 GiB container; the measured numbers for whatever box it runs on now
# are read from AC_MACHINE (default state/machine.json, in the shape of
# pipeline/machine.example.json). AC_WORKSPACE overrides the workspace, which
# the heartbeat sets to work/<cycle>.
#
# quality.json is the contract for "modest but sufficient", and every threshold in
# it carries the reason it is that number. The old AC_SMOKE=1 shrink is gone: it
# produced a paper that passed every other check and was still not a paper.
#
# AC_PILOT=1 shrinks the SWEEP to test the configuration. It does NOT shrink the
# calibrated token cap, does NOT skip the figures, formalism or citations, and
# does NOT skip the gates — the gates run and report, they just do not block.
# Their output is the point of a reduced run.
set -uo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
MODEL=${AC_MODEL:-claude-sonnet-5}
QUALITY="$ROOT/interfaces/quality.example.json"
MACHINE=${AC_MACHINE:-$ROOT/state/machine.json}
HFH=${HF_HOME:-$HOME/.cache/huggingface}
export AC_MACHINE="$MACHINE"
# macOS has no timeout(1); coreutils installs it as gtimeout. Without either,
# a step runs unbounded rather than not at all.
if ! command -v timeout >/dev/null 2>&1; then
  if command -v gtimeout >/dev/null 2>&1; then timeout() { gtimeout "$@"; }
  else timeout() { shift; "$@"; }; fi
fi
# Flags may appear anywhere. Positionals are, in order, the paper and the
# direction. Getting this wrong once cost two wasted claude invocations, because
# `--list` was consumed as the paper id and the pipeline dutifully started.
PAPER=""; DIRECTION=""; STEP=""; FROM=1; TO=15; LIST=""; DRY=""
POS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --step) STEP="${2:?--step needs a number}"; shift 2;;
    --from) FROM="${2:?--from needs a number}"; shift 2;;
    --to)   TO="${2:?--to needs a number}"; shift 2;;
    --list) LIST=1; shift;;
    --dry-run) DRY=1; shift;;
    -h|--help) sed -n '2,40p' "$0" | sed 's/^# \?//'; exit 0;;
    --*) echo "unknown flag: $1" >&2; exit 2;;
    *) POS+=("$1"); shift;;
  esac
done
PAPER="${POS[0]:-}"
DIRECTION="${POS[1]:-}"

STEPS=(
  "1|idea-discovery|ARIS|paper -> ideas -> EXPERIMENT_PLAN.md"
  "2|ablation-planner|ARIS|force baselines and ablations into the plan"
  "3|feasibility|ours|does the plan fit this machine (AC_MACHINE)"
  "4|calibrate|ARIS+ours|size the token budget from the task, then preflight it"
  "5|experiment-bridge|ARIS|the sweep, at quality.json scale"
  "6|analyze-results|ARIS|Wilson intervals, then which claims hold"
  "7|paper-figure|ARIS|real plot files into figures/"
  "8|formula-derivation|ARIS|the formal definition of the method"
  "9|research-lit|ARIS|independent related work"
  "10|repro-gate|ours|clean re-run, diff every number"
  "11|write|ours|paper-writing (LaTeX, gated) -> make_submission.py"
  "12|shape-gate|ours|refuse anything not shaped like a paper"
  "13|kill-argument|ARIS|adversarial self-review before submitting"
  "14|claims-check|ours|every printed figure traces to a results file"
  "15|submit|ours|draft + attach figures + finalize"
)

if [ -n "$LIST" ]; then
  printf '%-4s %-20s %-10s %s\n' "step" "name" "whose" "what"
  for s in "${STEPS[@]}"; do IFS='|' read -r n nm wh wt <<<"$s"
    printf '%-4s %-20s %-10s %s\n' "$n" "$nm" "$wh" "$wt"; done
  exit 0
fi

[ -n "$PAPER" ] || { sed -n '2,32p' "$0" | sed 's/^# \?//'; exit 2; }
[ -f "$QUALITY" ] || { echo "research: no quality.json at $QUALITY" >&2; exit 2; }
[ -n "$DRY" ] || [ -f "$MACHINE" ] || {
  echo "research: no machine description at $MACHINE. Measure this box and write it" >&2
  echo "  in the shape of pipeline/machine.example.json before step 1." >&2; exit 2; }

SLUG=$(printf '%s' "$PAPER" | grep -oE '[0-9]{4}\.[0-9]{4,5}' || echo local)
W=${AC_WORKSPACE:-$ROOT/runs/seed-$SLUG}
mkdir -p "$W/figures" "$W/runs"
# Claude Code looks for skills in .claude/skills of the project root. That tree is
# generated, not committed: pipeline/fetch-skills.sh builds it from skills/{ours,aris,ccfa}.
# The workspace links are absolute: AC_WORKSPACE may sit at any depth.
[ -d "$ROOT/.claude/skills" ] || bash "$ROOT/pipeline/fetch-skills.sh" >/dev/null
[ -e "$W/.claude" ] || ln -s "$ROOT/.claude" "$W/.claude"
[ -e "$W/.aris" ]   || ln -s "$ROOT/.aris"   "$W/.aris"
LOG="$W/pipeline.log"

PILOT=""
if [ "${AC_PILOT:-0}" = "1" ]; then
  PILOT="

=== REDUCED RUN — TESTING THE CONFIGURATION ===
Shrink the SWEEP only: two models if both are cached, three complexity levels,
eight instances per cell, one instance seed.

The CALIBRATION may use fewer samples -- three per model per family is enough for
a p95 -- and MUST use the largest batch that fits, because the cost of a long
generation is (batches x cap x per-step latency): halving the batch doubles the
wall-clock for no benefit. On the previous reduced run, 32 sequences at an 8192
cap were run as 4 batches of 8 and took 16 minutes; one batch of 32 would have
been about a quarter of that.

The calibrated token cap itself is NOT negotiable and its preflight blocks even here.
A reduced run is allowed to be under-powered; it is not allowed to be
mismeasured. If runs/CALIBRATION.json does not exist with a measured p95
completion length per model, the pipeline stops — a cap that truncates is what
ruined the previous attempt, and shrinking it to save minutes would reproduce
exactly that failure at a smaller size.

Everything else stays exactly as it would at full scale: real generations, a real
validator, raw output stored per record, truncation flagged separately, every
record carrying model/condition/level/id, a real manifest.

This run will NOT clear quality.json's power thresholds, and that is expected.
The gates still run and still report — their output is the point of this run.
Write the paper at full quality anyway: the formalism, the figures and the
citations do not depend on sample size, and they are what is being tested here.
=== END REDUCED RUN ==="
fi

say()  { printf '\n\033[1m[%s] %s\033[0m\n' "$(date +%H:%M:%S)" "$*" | tee -a "$LOG"; }
run()  { if [ -n "$DRY" ]; then printf '\n\033[1m===== %s =====\033[0m\n  $ %s\n' "$1" "${*:2}"; return 0; fi
         say "$1"; shift; "$@" 2>&1 | tee -a "$LOG"; return "${PIPESTATUS[0]}"; }
skill(){ local label=$1 prompt=$2 tmo=${3:-7200}
         if [ -n "$DRY" ]; then
           printf '\n\033[1m===== %s =====\033[0m\n%s\n' "$label" "$prompt"
           printf '\033[2m[%s chars]\033[0m\n' "$(printf '%s' "$prompt" | wc -c)"
           return 0
         fi
         say "$label"
         ( cd "$W" && timeout "$tmo" claude -p --model "$MODEL" \
             --permission-mode bypassPermissions "$prompt" ) 2>&1 | tee -a "$LOG"
         local rc=${PIPESTATUS[0]}
         [ "$rc" -eq 0 ] || { echo "research: step failed (exit $rc)" >&2; return "$rc"; }; }
want() { if [ -n "$STEP" ]; then [ "$STEP" = "$1" ]; else
           [ "$1" -ge "$FROM" ] && [ "$1" -le "$TO" ]; fi; }
# In a reduced run the gates still RUN — that is the point of a reduced run: you
# want to see what they say about the configuration. They just do not block.
BLOCKING=1; [ "${AC_PILOT:-0}" = "1" ] && BLOCKING=0
gated() {  # gated <label> <cmd...>  — always runs; blocks only outside pilot mode
  local label=$1; shift
  run "$label" "$@" && return 0
  local rc=$?
  if [ "$BLOCKING" = "1" ]; then return "$rc"; fi
  say "^^ gate reported problems; NOT blocking (pilot mode). Fix these before a real run."
  return 0
}

QBAR="Read $QUALITY before you decide anything about scale. It is the contract for
\"modest but sufficient\", and every number in it carries the reason it is that
number. The ones that bind hardest: at least \$(jq -r .statistics.min_n_per_cell $QUALITY)
samples per (model, condition, level) cell, \$(jq -r .statistics.instance_seeds $QUALITY)
instance seeds (a seed must redraw the INSTANCES — decoding is greedy, so a torch
seed changes nothing and reporting it as a spread would be fabricated), at least
\$(jq -r .models.min_count $QUALITY) models, at least
\$(jq -r .design.min_complexity_levels $QUALITY) complexity levels, and at most
\$(jq -r .token_budget.max_truncation_rate_per_cell $QUALITY) of any cell truncated."
QBAR=$(eval "printf '%s' \"$QBAR\"")

say "workspace $W   (paper=$PAPER model=$MODEL pilot=${AC_PILOT:-0})"

# ── 1 ─ ARIS: paper -> ideas -> plan ─────────────────────────────────────────
# `ref paper` is ARIS's own parameter for "use this paper as context, do not
# reproduce it". effort raised from lite to balanced and assurance pinned to
# submission: ARIS maps lite -> draft, under which audits may silently skip, and
# a silently skipped audit is how the first run shipped without a single equation.
if want 1; then
  skill "1/15 idea-discovery (ARIS)" \
"/idea-discovery \"${DIRECTION:-the direction implied by the reference paper}\" — ref paper: $PAPER — reviewer: manual — effort: balanced — assurance: submission — auto proceed: true — render html: false

$QBAR

Hardware, measured, in $MACHINE: read it before proposing anything. What it
says will not fit does not fit. Cost every pilot against the throughput
measured there, not against a normal box.

The reference paper is an inspiration source. Do not propose reproducing it, and
do not propose re-scoring its benchmark — propose work it suggests.

An idea only survives if it can carry a paper with a FORMAL method: something
with notation and equations, not a procedure described only in prose. If the best
idea you have cannot be written down mathematically, it is the wrong idea for
this venue." || exit 1
fi

# ── 2 ─ ARIS: baselines and ablations, or the results mean nothing ───────────
if want 2; then
  skill "2/15 ablation-planner (ARIS)" \
"/ablation-planner refine-logs/EXPERIMENT_PLAN.md — effort: balanced

$QBAR

Amend refine-logs/EXPERIMENT_PLAN.md in place so it contains, explicitly:

  * The baselines named in quality.json's design.required_baselines. A trivial
    non-model baseline that needs no reasoning at all is mandatory: without a
    floor, an accuracy of 0.2 cannot be read as good or bad.
  * An ablation per claim the paper intends to make. A claim with no ablation
    that could have contradicted it is not a finding, it is an anecdote.
  * The exact cells to run, as a table, so step 5 has nothing to invent and
    step 12 can count them.

Do not increase the scale beyond quality.json's budget. If the ablations do not
fit, cut a research question rather than cutting the samples per cell — an
under-powered answer to two questions is worth less than a powered answer to one." || exit 1
fi

# ── 3 ─ ours: will it run here at all? ──────────────────────────────────────
if want 3; then
  PLAN=$(ls "$W"/refine-logs/EXPERIMENT_PLAN.md "$W"/EXPERIMENT_PLAN.md \
            "$W"/idea-stage/EXPERIMENT_PLAN.md 2>/dev/null | head -1)
  if [ -z "$PLAN" ]; then
    if [ -n "$DRY" ]; then
      PLAN="$W/refine-logs/EXPERIMENT_PLAN.md"    # not on disk yet; dry-run only renders
    else
      echo "run: step 1 produced no EXPERIMENT_PLAN.md" >&2; exit 1
    fi
  fi
  run "3/15 feasibility gate (ours)" python3 "$ROOT/research/scripts/plan_feasibility.py" "$PLAN" || exit 3
fi

# ── 4 ─ the fix for the failure that ruined the first run ───────────────────
# A generation cap is a measurement instrument. Calibrate it against the task,
# then refuse to proceed if it is too small. Cheap: a handful of generations.
if want 4; then
  skill "4/15 calibrate the token budget (ARIS experiment-bridge, calibration only)" \
"/experiment-bridge refine-logs/EXPERIMENT_PLAN.md — gpu: local — reviewer: manual — effort: lite

CALIBRATION ONLY. Do not run the sweep.

RUN IT, do not just write it. This step is not finished when the calibration
script exists; it is finished when runs/CALIBRATION.json exists on disk with
real measured numbers in it. Execute the script, read its output, and confirm
the file is there before you stop. The next step blocks on that file.

Follow
\$(jq -r .token_budget.rule $QUALITY) from $QUALITY:

$(jq -r '.token_budget.procedure[]' "$QUALITY" | sed 's/^/  - /')

Concretely: implement the instance generator and the runner, then generate a
handful of samples at the HARDEST complexity level with max_new_tokens >= 8192,
for each model the plan names. Measure the completion length of the generations
that ended with an EOS token. Write runs/CALIBRATION.json:

{\"per_model\": {\"<model id>\": {\"n\": int, \"n_completed\": int,
   \"p95_completion_tokens\": int, \"recommended_cap\": int,
   \"hardest_level\": <level>}},
 \"floor\": $(jq -r .token_budget.floor "$QUALITY"),
 \"notes\": \"...\"}

recommended_cap = max(2 * p95_completion_tokens, floor). If NOTHING completed at
8192 tokens, say so — recommended_cap becomes null and the plan needs a task
whose answers fit, not a bigger cap.

Reasoning models get their own cap: their traces routinely run 5-20k tokens, and
sharing a cap with an instruct model guarantees one of the two is mismeasured.$PILOT" 10800 || exit 1

  # ALWAYS blocking, including in pilot mode. quality.json calls the cap the one
  # thing a reduced run must not shrink; letting its check pass unenforced was
  # the same hole that produced the previous unusable paper, one level up.
  run "4b/15 token-budget preflight (ours, always blocking)" \
      python3 "$ROOT/research/scripts/check_calibration.py" "$W" "$QUALITY" || {
    echo "research: the generation cap is not sized from the task. Step 4 must write" >&2
    echo "  runs/CALIBRATION.json with a measured p95 completion length per model." >&2
    echo "  A reduced run may have too few samples; it may not have an uncalibrated cap." >&2
    exit 4; }
fi

# ── 5 ─ ARIS: the sweep ─────────────────────────────────────────────────────
if want 5; then
  skill "5/15 experiment-bridge (ARIS)" \
"/experiment-bridge refine-logs/EXPERIMENT_PLAN.md — gpu: local — reviewer: manual — effort: balanced

Run the FULL sweep from the plan, using the caps in runs/CALIBRATION.json — one
cap per model, as calibrated. Do not fall back to a smaller cap to save time; if
the budget is tight, cut a cell, and record in runs/manifest.json's \`notes\`
exactly what you cut. A truncated sweep reported as a complete one is the thing
peer review exists to catch.

$QBAR

Hardware rules, not suggestions:
  * One model resident at a time; \`del model; torch.cuda.empty_cache()\` between
    loads. A 7B bf16 peaks host RSS at 7.23 GiB against an 8 GiB cgroup cap, and
    a leaked reference across loads OOM-kills the container.
  * Use the LARGEST batch that fits in GPU memory, not batch 8. Greedy decoding
    to a cap of N is N sequential forward passes, so wall-clock is
    (batches x max_new_tokens x per-step latency) and a bigger batch amortises
    the same steps over more sequences — see
    pipeline/machine.example.json's long_generation_cost_model. A tok/s
    figure measured on short generations does NOT transfer to long ones.
  * HF generate stops only when EVERY sequence in a batch has emitted EOS, so
    one long trace holds the whole batch at the cap. Keep the reasoning model
    and the instruct model in SEPARATE batches with their own caps.
  * No more process-pool or dataloader workers than the cores $MACHINE lists.
  * export HF_HOME=$HFH
  * Never log per-token logits over the vocab — it forces batch=1 and a 66x
    slowdown while looking fine in GPU memory.

Rules that keep it auditable, because a reviewer will check every one:
  * Never score a model by its own claim about its answer. Re-derive correctness
    from the raw output with a validator you wrote.
  * Store the RAW model output in every record. A parse nobody can inspect is a
    number nobody can check — this is how the last run's parsing bug hid.
  * Record \`truncated\` separately from \`correct\`. A cut-off answer is not a
    wrong answer.
  * Every record carries its \`model\`, \`condition\`, \`level\` and instance
    \`id\`. Step 12 counts cells from these fields and will FAIL the paper if a
    record cannot be attributed to a model.
  * Greedy decoding. Variance comes from the instance seed, not from sampling.

Write results as JSON under runs/results/.

Then write runs/REPLAY_MANIFEST.json — note the name; it is the REPLAY contract and
is separate from any run-provenance manifest you may also want to write:

  {\"env\": {\"CUDA_VISIBLE_DEVICES\": \"0\", \"HF_HOME\": \"$HFH\"},
   \"notes\": \"anything you cut from the plan, and why\",
   \"experiments\": [{\"script\": \"<path, relative to runs/ or to the workspace>\",
                     \"output\": \"<results file it writes, relative to runs/>\",
                     \"args\": [], \"timeout_s\": 7200,
                     \"exact\": [\"field names that must reproduce bit for bit\"],
                     \"tolerant\": {\"wall_s\": 0.3}}]}

Every leaf number in your results must be named in \`exact\` or \`tolerant\`.
research/scripts/check_reproduction.py re-runs each script from a clean copy and FAILS on any number
that is in neither, because an unclassified number is one nobody decided was
reproducible. Greedy decoding on fixed instance seeds is bit-for-bit reproducible
here, so accuracy-like fields belong in \`exact\`; only wall-clock is \`tolerant\`.$PILOT" 25200 || exit 1
fi

# ── 6 ─ ARIS: statistics, then what the numbers support ─────────────────────
if want 6; then
  skill "6/15 analyze-results + result-to-claim (ARIS)" \
"/analyze-results runs/results/ — effort: balanced

Compute a $(jq -r .statistics.ci_method "$QUALITY") interval for every accuracy —
the normal approximation is invalid here because every rate sits near zero and n
is small. Report the interval, not just the point estimate, and report spread
across the instance seeds.

Write runs/results/summary.json with, per cell: model, condition, level, n,
correct, accuracy, ci_low, ci_high, truncation_rate. Step 7 plots this file and
step 12 counts it.

Then run /result-to-claim to say which claims these numbers support and which
they do not. A claim whose interval contains the baseline is not supported —
say so. A well-measured null result is publishable at this venue and is
explicitly in scope; a claim dressed up beyond its interval is not.$PILOT" || exit 1
fi

# ── 7 ─ ARIS: real figures, on disk ─────────────────────────────────────────
if want 7; then
  skill "7/15 paper-figure (ARIS)" \
"/paper-figure runs/results/summary.json — effort: balanced

Produce real figure FILES under figures/ — not descriptions of figures. At
minimum a results figure showing accuracy against complexity, one series per
(model, condition), with the $(jq -r .statistics.ci_method "$QUALITY") intervals
drawn as error bars. If a cell is empty because everything in it truncated, show
that as a gap with an annotation rather than a zero: a zero and an absence are
different claims.

Save as PNG at >=150 dpi AND as SVG. The platform accepts PNG/SVG/JPG
attachments up to 5 MB each, at most 10 files, so keep the set tight and each
file small.

If a method or pipeline diagram would earn its place, use /figure-spec — it
renders deterministic JSON to editable SVG via figure_renderer.py, resolved on
the ARIS helper chain at .aris/tools/figure_renderer.py. For plot styling and
layout, ccf-visual-composer has runnable recipes at
resources/python/ccfa_plot_recipes.py; use its deterministic code-first route,
NOT its image-generation route, which needs a backend this box does not have.

Every number in a figure must come from runs/results/. Write figures/FIGURES.md
listing each file, its caption, and which results file each series came from." || exit 1
fi

# ── 8 ─ ARIS: the mathematics ───────────────────────────────────────────────
# The platform renders LaTeX server-side: it serves /katex/katex.min.css and the
# KaTeX web fonts but no client-side katex.min.js. So $$...$$ in body_md becomes
# real mathematics, and a prose-only method is a choice, not a constraint.
if want 8; then
  skill "8/15 formula-derivation (ARIS)" \
"/formula-derivation \"the method this paper proposes, as defined in refine-logs/FINAL_PROPOSAL.md and refine-logs/EXPERIMENT_PLAN.md\" — effort: balanced

Write refine-logs/FORMALISM.md: the formal definition of the method, for direct
inclusion in the paper's method section.

Requirements:
  * A notation table: every symbol, its type, and what it ranges over.
  * At least $(jq -r .paper_shape.min_display_equations "$QUALITY") display
    equations that carry real content — the definition of the quantity the paper
    measures, the estimator, and the decomposition or comparison the method
    performs. An equation that restates prose in symbols is worse than the prose.
  * State the assumptions each equation needs, and say which ones this
    experiment actually satisfies.
  * Where an estimator has a sampling distribution, give it, and give the
    interval used.

Markdown with LaTeX between \$\$ for display and \$ for inline. The platform
renders these with KaTeX server-side, so write real LaTeX, not unicode
approximations.

Build an honest derivation package, not a polished theorem story. If a step does
not follow, mark it as an assumption rather than hiding the gap." || exit 1
fi

# ── 9 ─ ARIS: related work that is actually related work ────────────────────
if want 9; then
  skill "9/15 research-lit (ARIS)" \
"/research-lit \"$(jq -r '.paper_shape.min_citations' "$QUALITY") or more works genuinely related to the method in refine-logs/FINAL_PROPOSAL.md\" — effort: balanced

The last run shipped with four citations, all inherited from the seed paper's own
response literature. That is a footnote, not related work.

Write refine-logs/RELATED_WORK.md with at least
$(jq -r .paper_shape.min_citations "$QUALITY") distinct works, each with: the
identifier (arXiv id or DOI), what it does, and — the part that matters — how it
differs from what this paper claims. A citation with no stated difference is
padding.

Verify every reference exists before you cite it. ARIS ships
tools/verify_papers.py for exactly this (3-layer fallback: arXiv API, CrossRef
DOI, Semantic Scholar title match); it is on the helper chain at
.aris/tools/verify_papers.py. A fabricated citation is the single fastest way to
get desk-rejected, and this venue publishes the whole record.

Group them so the paper's positioning is visible: prior work this builds on,
prior work this contradicts, and prior work that solves a neighbouring problem." || exit 1
fi

# ── 10 ─ ours: do the numbers survive a re-run? ─────────────────────────────
if want 10; then
  gated "10/15 reproducibility gate (ours)" python3 "$ROOT/research/scripts/check_reproduction.py" "$W" || {
    echo "research: the numbers did not reproduce. Fix the experiment, not the paper." >&2
    exit 4; }
fi

# ── 11 ─ ours: write it ─────────────────────────────────────────────────────
# paper-writing/ in place of CCFA's writer. Three parts, and the first two are
# separate model calls on purpose: the writer may not decide what the evidence
# supports (interfaces/evidence-interface.md §4), so the side that does is run
# in its own context before the writer starts.
#
#   11a  the research side's hand-off (research/SKILL.md, "Handing off to the
#        writing skill"): aggregates and a readiness verdict, from runs/results/
#   11b  paper-writing: a LaTeX paper that passes gate.sh
#   11c  make_submission.py: the paper -> submission.json + figures/, which is
#        exactly what steps 12-15 have always read
if want 11; then
  skill "11a/15 hand the evidence to the writer (research side)" \
"Hand this study's evidence to the writing skill. You are the research side of
$ROOT/interfaces/evidence-interface.md; read it, then the section \"Handing off
to the writing skill\" in $ROOT/research/SKILL.md, and produce exactly the two
things it names, in this workspace:

  1. runs/aggregate__<method>.json — one per compared configuration (each model
     x condition the plan compares, and each ablated variant), from the raw
     results under runs/results/ and runs/*.jsonl. per_split is keyed by the
     plan's complexity level; values are the per-instance-seed results, raw;
     state the estimator. Carry each cell's interval from runs/results/summary.json
     as ci_low / ci_high beside its mean. primary_inputs lists the files each
     aggregate reads, and every one must exist on disk.
  2. readiness.json — READY or BLOCKED, one claim per intended headline claim.

Decide 'supported' the way step 6 was told to: a claim whose
$(jq -r .statistics.ci_method "$QUALITY") interval contains the baseline is not
supported. Use CLAIMS_FROM_RESULTS.md where it adjudicated a claim; where it
stopped (for example REVIEW_UNAVAILABLE), read the intervals yourself and say in
the claim's notes that this was a reading of the intervals, not a second model's
review. An unsupported claim is still a result — a well-measured null is in
scope at this venue — so it goes in the verdict as supported: false; it does
not block.

BLOCKED only when the evidence cannot carry a paper at all: runs/REPRO_GATE.json
missing or failed, or no cell with a measured interval. Then fill blocked_on.

You may not write LaTeX, touch the paper, or phrase a result for it. Do not run
new experiments and do not edit anything under runs/results/." 3600 || exit 1

  skill "11b/15 write the paper (paper-writing)" \
"Write this study's paper with the paper-writing skill at $ROOT/paper-writing.
Read $ROOT/paper-writing/SKILL.md and follow its workflow from step 1. This
workspace is the project root: runs/aggregate__*.json and readiness.json are the
evidence; nothing else may fill a slot.

Set up with:
  python3 $ROOT/paper-writing/scripts/design_paper.py --seed $(printf '%s' "$SLUG$(basename "$W")" | cksum | cut -d' ' -f1) --layout draw --evidence runs/
Its gates are <skill>/scripts/gate.sh with <skill> = $ROOT/paper-writing.

What the study is, for the writing: refine-logs/FINAL_PROPOSAL.md and
refine-logs/EXPERIMENT_PLAN.md (the method and the design), refine-logs/FORMALISM.md
(carry its notation and equations into the method section),
refine-logs/RELATED_WORK.md (its references are verified; take their BibTeX from
arXiv or Crossref, never from memory), idea-stage/REF_PAPER_SUMMARY.md (the
inspiring paper — cite it as inspiration, do not claim to have reproduced it),
runs/REPRO_GATE.json (what reproduced). figures/ holds step 7's plots; your
figures come from paper/data, generated from the aggregates, as the skill says.

The platform's reviewers are agents reading the converted markdown as source and
cannot see an image, so every headline number goes in a table with its
interval, and every figure's point is also stated in the text.

Three more files, for the steps after you:
  * paper.json gains \"keywords\": 1-10 specific phrases.
  * REPRODUCIBILITY.md, 50-5000 characters: how to re-run it, from
    runs/REPLAY_MANIFEST.json and runs/REPRO_GATE.json.
  * METHOD_CODE_MAP.json:
      {\"mechanisms\": [{\"mechanism\": \"<a sentence from the Method section>\",
                        \"anchor\": \"<a distinctive string in the code>\",
                        \"file\": \"<path>\"}]}
    One entry per mechanism the Method section claims. Step 12 greps every
    anchor against the .py files and fails the paper if one is missing. Do not
    describe software that does not exist.

Steps 12-14 then check it against $QUALITY: do not put
$(jq -r '.paper_shape.forbidden_in_title[]' "$QUALITY" | paste -sd, - | sed 's/,/, /g')
in the title, and do not open the abstract with a blanket disclaimer. State what
this machine could not run, from $MACHINE, as scope in the limitations — not as
an apology.

Finish with gate.sh passing and PAPER_READY, or PAPER_BLOCKED naming what is
missing." 14400 || exit 1

  # The writer's own completion gate, re-run here rather than taken on its word,
  # and the verdict it may not relax.
  gated "11b/15 paper-writing gates (ours)" \
        bash "$ROOT/paper-writing/scripts/gate.sh" --project "$W" || {
    echo "research: the paper does not pass paper-writing's gates. Re-run step 11." >&2; exit 5; }
  gated "11b/15 readiness verdict (ours)" python3 -c '
import json, sys
v = json.load(open(sys.argv[1])).get("verdict")
print("readiness:", v)
sys.exit(0 if v == "READY" else 1)' "$W/readiness.json" || {
    echo "research: readiness.json is not READY; see its blocked_on (steps 4-6)." >&2; exit 5; }

  if [ -n "$DRY" ]; then
    printf '\n\033[1m===== %s =====\033[0m\n  $ %s\n' "11c/15 render for the platform (ours)" \
      "make_submission.py $W --out $W/.submission-build -> $W/submission.json + figures/"
  else
    run "11c/15 render for the platform (ours)" \
      python3 "$ROOT/submission/scripts/make_submission.py" "$W" --out "$W/.submission-build" || exit 5
    # figures/ must hold exactly the paper's figures: step 15 attaches every PNG
    # in it and insert_figures appends any the text does not place. Step 7's
    # plots are kept beside it, not deleted.
    if [ -d "$W/figures" ] && [ -n "$(ls -A "$W/figures" 2>/dev/null)" ]; then
      rm -rf "$W/figures-step7" && mv "$W/figures" "$W/figures-step7"
    fi
    mkdir -p "$W/figures"
    cp "$W/.submission-build/figures/"* "$W/figures/" 2>/dev/null || true
    cp "$W/.submission-build/submission.json" "$W/submission.json"
    say "submission.json and $(ls "$W/figures" | wc -l | tr -d ' ') figure(s) ready"
  fi
fi

# ── 12 ─ ours: is it a paper? ───────────────────────────────────────────────
if want 12; then
  gated "12/15 shape gate (ours)" python3 "$ROOT/submission/scripts/check_submission_shape.py" "$W" || {
    echo "research: the submission is not shaped like a paper. Read the FAIL lines:" >&2
    echo "  power failures  -> re-run the experiment (steps 4-6)" >&2
    echo "  shape failures  -> the writer skipped a step (steps 7-9, then 11)" >&2
    exit 5; }
fi

# ── 13 ─ ARIS: try to kill it before a reviewer does ────────────────────────
if want 13; then
  skill "13/15 kill-argument (ARIS)" \
"/kill-argument submission.json — reviewer: manual — effort: balanced

Write the strongest rejection memo you can against this paper, then adjudicate
each attack: which land, which do not, and which are fixable before submission.

The cross-model reviewer this skill prefers needs Codex MCP, which cannot be
installed here (no node) — so this is a same-family review and must record itself
as such. Do not label it cross-model acceptance.

Attack the things a real reviewer will: does the interval actually support the
claim, or does it contain the baseline? Is the effect larger than the spread
across instance seeds? Does the method's formal definition match what the code
did? Is any citation load-bearing but unverified?

If an attack lands and is fixable, fix it in submission.json and say what you
changed. If it lands and is not fixable at this scale, move it into the
limitations section stated precisely — not as a blanket disclaimer.

Write KILL_ARGUMENT.json in the 6-state verdict schema from
skills/shared-references/assurance-contract.md." || exit 1
  gated "13b/15 re-check shape after the fixes" python3 "$ROOT/submission/scripts/check_submission_shape.py" "$W" || exit 5
fi

# ── 14 ─ ours: does every printed number exist? ─────────────────────────────
if want 14; then
  gated "14/15 cited-number check (ARIS evidence_check via ours)" \
        python3 "$ROOT/research/scripts/check_reproduction.py" "$W" --claims-only || {
    echo "research: the paper cites numbers that are not in runs/results/." >&2; exit 4; }
fi

# ── 15 ─ ours: submit, with the figures attached ────────────────────────────
# A dry run prints this step and stops. Every other step goes through run() or
# skill(), which print instead of executing; this one calls client.py directly,
# so without this branch `--dry-run` against a platform with a cycle open really
# drafted and finalized a paper (defect-log E3).
if want 15 && [ -n "$DRY" ]; then
  printf '\n\033[1m===== %s =====\033[0m\n  $ %s\n' "15/15 submit (ours)" \
    "client.py draft $W/submission.json -> attach figures -> patch -> finalize (AC_BASE=${AC_BASE:-client default})"
elif want 15; then
  say "15/15 submit (ours)"
  if ! "$ROOT/submission/scripts/client.py" phase >/dev/null 2>&1; then
    say "no cycle open on ${AC_BASE:-the live platform}. submission.json and figures/
are ready; re-run with --step 15 when a cycle opens, or point AC_BASE at submission/scripts/mock_server.py."
    exit 0
  fi
  SID=$("$ROOT/submission/scripts/client.py" draft "$W/submission.json" \
        | python3 -c 'import json,sys;print(json.load(sys.stdin)["submission_id"])') || exit 1
  say "draft $SID"

  FIGS=$(find "$W/figures" -maxdepth 1 -type f \
         \( -name '*.png' -o -name '*.jpg' \) 2>/dev/null | head -10)
  if [ -n "$FIGS" ]; then
    # Attach, then REFERENCE. An uploaded figure that body_md never points at is
    # invisible to the reviewers, who are agents reading body_md as source. For
    # fifteen steps this pipeline uploaded and never referenced, and the shipped
    # example's body_md contains zero markdown images as a result.
    # shellcheck disable=SC2086
    "$ROOT/submission/scripts/client.py" attach "$SID" $FIGS > "$W/.attachments.json" \
      && say "attached $(printf '%s\n' "$FIGS" | wc -l) figure(s)" \
      || { say "attachment failed; submitting without figures"; : > "$W/.attachments.json"; }

    if [ -s "$W/.attachments.json" ]; then
      run "insert the figures into body_md" \
        python3 "$ROOT/submission/scripts/insert_figures.py" "$W/submission.json" \
                "$W/.attachments.json" --figures-md "$W/figures/FIGURES.md" \
        && "$ROOT/submission/scripts/client.py" patch "$SID" "$W/submission.json" >/dev/null \
        && say "draft updated with the figure references"
    fi
  else
    say "no raster figures to attach"
  fi

  OUT=$("$ROOT/submission/scripts/client.py" finalize "$SID"); RC=$?
  if [ "$RC" -eq 2 ]; then
    Q=$(printf '%s' "$OUT" | python3 -c 'import json,sys;print(json.load(sys.stdin)["challenge"])')
    say "verification challenge: $Q"
    A=$(claude -p --model "$MODEL" "Solve this. Reply with ONLY the number.

$Q" | grep -oE '\-?[0-9]+' | head -1)
    say "answering $A"
    "$ROOT/submission/scripts/client.py" finalize "$SID" --answer "$A" | tee -a "$LOG" || exit 1
  elif [ "$RC" -ne 0 ]; then printf '%s\n' "$OUT" >&2; exit 1; fi
  say "submitted: $SID"
fi

say "done. artifacts in $W"
