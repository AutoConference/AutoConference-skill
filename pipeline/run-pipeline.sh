#!/usr/bin/env bash
# research -- one inspiring paper in, one real paper out.
#
#   pipeline/run-pipeline.sh 2506.06941 "evaluation methodology for reasoning models"
#   pipeline/run-pipeline.sh "" "sample-efficient exploration in bandits"   # no seed paper
#   pipeline/run-pipeline.sh 2506.06941 "" --from 7        # resume
#   pipeline/run-pipeline.sh --list                        # the step table
#
# The paper is an INSPIRATION SOURCE, not a reproduction target.
#
# Every research step is an existing skill from skills/aris (ARIS) or, for plot
# recipes, skills/ccfa (CCFA-Skills). We own these, because nothing upstream
# provides them:
#
#   step  3  research/scripts/plan_feasibility.py       ARIS assumes a normal GPU box; this pipeline
#                               was built in a 2-core, 8 GiB container. Scores the
#                               plan against the measured machine before code exists.
#   step  4  the calibration    A generation cap is a measurement instrument. The
#            preflight          first version of this pipeline capped at 512 tokens
#                               on a task needing more, truncated 9 of 15 samples,
#                               and destroyed its own primary measurement. Now the
#                               cap is derived from the task and checked.
#   step  9  research/scripts/check_related_work.py  Every reference exists and is the paper its id
#                               names, each states how it differs, enough of them.
#   step 10  research/scripts/check_reproduction.py  ARIS gates on a cross-model reviewer via Codex MCP;
#                               no node here, so we re-run and diff instead.
#   step 12  submission/scripts/check_submission_shape.py  Refuses a submission that is not shaped like a
#                               paper: no equations, no figure, four citations, a
#                               title calling itself a pilot. Thresholds live in
#                               quality.json, which says why each one is what it is.
#   step 13  research/scripts/check_kill_argument.py  Reads KILL_ARGUMENT.json and computes its verdict
#                               from the points; a critical one still standing stops.
#   step 15  submission/scripts/client.py             The AutoConference protocol. Nothing upstream speaks it.
#
# Step 11 is paper-writing/, not CCFA's writer: a LaTeX paper that passes its
# own gates, rendered into submission.json by make_submission.py. Steps 12-15
# read the same files they always did.
#
# Any coding-agent CLI runs the steps: every model turn goes through
# pipeline/agent-turn.sh, which picks the backend (AC_BACKEND) the same way the
# heartbeat does.
#
# Three kinds of study, recorded by step 3 in <workspace>/STUDY_KIND:
#   llm-generation  measures what language models generate. Everything below
#                   was built for this kind and applies to it unchanged,
#                   including the token-budget calibration of step 4.
#   computational   any other experiment. The general rules apply; step 4 is
#                   skipped.
#   theory          the contribution is derivations; the experiments are small
#                   numerical checks of them. What a machine without a GPU
#                   is steered to.
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
MODEL=${AC_MODEL:-}
QUALITY="$ROOT/interfaces/quality.example.json"
MACHINE=${AC_MACHINE:-$ROOT/state/machine.json}
HFH=${HF_HOME:-$HOME/.cache/huggingface}
export AC_MACHINE="$MACHINE"
# jq is not installed on most Linux machines; the handful of filters used here
# have a stand-in, so it is not a prerequisite.
command -v jq >/dev/null 2>&1 || jq() { python3 "$ROOT/pipeline/mini_jq.py" "$@"; }
# macOS has no timeout(1); coreutils installs it as gtimeout. Without either,
# a step runs unbounded rather than not at all.
if ! command -v timeout >/dev/null 2>&1; then
  if command -v gtimeout >/dev/null 2>&1; then timeout() { gtimeout "$@"; }
  else timeout() { [ "$1" = --foreground ] && shift; shift; "$@"; }; fi
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

[ -n "$PAPER$DIRECTION" ] || { sed -n '2,32p' "$0" | sed 's/^# \?//'; exit 2; }
[ -f "$QUALITY" ] || { echo "research: no quality.json at $QUALITY" >&2; exit 2; }
[ -n "$DRY" ] || [ -f "$MACHINE" ] || {
  echo "research: no machine description at $MACHINE. Measure this box and write it" >&2
  echo "  in the shape of pipeline/machine.example.json before step 1." >&2; exit 2; }

SLUG=$(printf '%s' "$PAPER" | grep -oE '[0-9]{4}\.[0-9]{4,5}' || echo local)
W=${AC_WORKSPACE:-$ROOT/runs/seed-$SLUG}
mkdir -p "$W/figures" "$W/runs"
# Claude Code looks for skills in .claude/skills of its working directory. That
# tree is generated, not committed: pipeline/fetch-skills.sh builds it from
# skills/{aris,ccfa} under state/skill-mount, outside the kit root so the inbox
# duties never see it, and each workspace links to it. The links are absolute:
# AC_WORKSPACE may sit at any depth.
MOUNT="$ROOT/state/skill-mount/.claude"
[ -e "$MOUNT/skills/idea-discovery/SKILL.md" ] || bash "$ROOT/pipeline/fetch-skills.sh" >/dev/null
[ -e "$W/.claude" ] || ln -s "$MOUNT" "$W/.claude"
[ -e "$W/.aris" ]   || ln -s "$ROOT/.aris"   "$W/.aris"
LOG="$W/pipeline.log"

# The study kind, from step 3. A dry run has none yet and shows the steps as the
# pipeline's original kind would see them (AC_STUDY_KIND picks another).
KIND=""
[ -f "$W/STUDY_KIND" ] && KIND=$(tr -d '[:space:]' < "$W/STUDY_KIND")
case "$KIND" in llm-generation|computational|theory) ;; *) KIND="" ;; esac
[ -z "$KIND" ] && [ -n "$DRY" ] && KIND=${AC_STUDY_KIND:-llm-generation}
need_kind() { [ -n "$KIND" ] || {
  echo "research: no study kind in $W/STUDY_KIND. Step 3 records it; run step 3 first." >&2; exit 3; }; }

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

# Every model call a step makes is appended here, for the heartbeat's turn
# record; the feasibility gate (a Python script) appends its own.
export AC_STEP_PROMPTS="$W/.step-prompts"
say()  { printf '\n\033[1m[%s] %s\033[0m\n' "$(date +%H:%M:%S)" "$*" | tee -a "$LOG"; }
run()  { if [ -n "$DRY" ]; then printf '\n\033[1m===== %s =====\033[0m\n  $ %s\n' "$1" "${*:2}"; return 0; fi
         say "$1"; shift; "$@" 2>&1 | tee -a "$LOG"; return "${PIPESTATUS[0]}"; }
# Deadline awareness (A17). The heartbeat passes the cycle's submission
# deadline; every model turn is told it, and in the last AC_WRAPUP_HOURS the
# instruction turns from "plan against it" to "stop expanding and finish".
deadline_note() {
  [ -n "${AC_SUBMISSION_CLOSES_AT:-}" ] || return 0
  python3 - "$AC_SUBMISSION_CLOSES_AT" "${AC_WRAPUP_HOURS:-12}" "${AC_PIPELINE:-sync}" <<'DEADLINE'
import sys, datetime as dt
closes = dt.datetime.fromisoformat(sys.argv[1].replace("Z", "+00:00"))
wrap = float(sys.argv[2])
left = (closes - dt.datetime.now(dt.timezone.utc)).total_seconds() / 3600
if sys.argv[3] == "async":
    # B02: a new conference every 7 days, opening the moment one closes. A
    # paper finished late goes to the next one and can go to review at once,
    # so there is nothing to rush -- and the deadline this step was given may
    # already belong to a conference that has closed.
    print(f"=== SCHEDULE ===\nConferences here run every 7 days, and the next opens the moment one closes: a paper finished after {sys.argv[1]} UTC goes to the next conference, and nothing is lost. Size this step for a sound study, not for the deadline. The sooner the paper is done and confirmed, the longer you will have to answer its reviews.\n=== END SCHEDULE ===\n")
elif left <= 0:
    print(f"=== DEADLINE PASSED ===\nThe submission window closed at {sys.argv[1]} UTC. Do not start anything new.\n=== END DEADLINE ===\n")
elif left <= wrap:
    print(f"=== WRAP UP NOW ===\nThe submission window closes at {sys.argv[1]} UTC, {left:.1f} hours from now. Do not start new experiments or widen the study. Finish what is running, record results exactly as they are (a smaller study honestly reported beats a larger one that misses the deadline), and move on so the paper can be written and submitted in time.\n=== END WRAP UP ===\n")
else:
    print(f"=== DEADLINE ===\nThe submission window closes at {sys.argv[1]} UTC, {left:.1f} hours from now. Writing, checking and submitting take the last {wrap:.0f} hours. Size this step so the whole study fits before then; if it cannot, scale it down now rather than extend it later.\n=== END DEADLINE ===\n")
DEADLINE
}
# What the owner gave this agent to work with (A21, A01), what it learned from
# past reviews (A20), and the owner's own additions to the kit (A21), put in
# front of every research step:
#   AC_GPUS=0,1 | none      the GPUs it may use; CUDA_VISIBLE_DEVICES is set
#                           to them for every step, so others stay unseen
#   AC_COMPUTE_NOTES=...    anything else: a cluster, its queue, its limits
#   AC_BUDGET_NOTES=...     the owner's budget, in tokens, hours or money
#   state/strategy/*.md     its research strategy, rewritten after each cycle
#   custom/all.md           the owner's instructions for every step,
#   custom/website.md       those they wrote on the website (KIT-008), and
#   custom/step-<N>.md      for step N; custom/ is theirs, and `git pull`
#                           never touches it
owner_context() {
  local label=$1 n base f
  n=${label%%/*}; base=$(printf '%s' "$n" | tr -dc '0-9')
  if [ -n "${AC_GPUS:-}${AC_COMPUTE_NOTES:-}${AC_BUDGET_NOTES:-}" ]; then
    printf '=== WHAT YOUR OWNER GAVE YOU ===
'
    case "${AC_GPUS:-}" in
      '') ;;
      none|NONE) printf 'GPUs: none. Plan CPU-scale work.
' ;;
      *) printf 'GPUs: %s (CUDA_VISIBLE_DEVICES is set to exactly these; use no others). Use them: size the study to what they can do, not to a toy.
' "$AC_GPUS" ;;
    esac
    [ -n "${AC_COMPUTE_NOTES:-}" ] && printf 'Compute: %s
' "$AC_COMPUTE_NOTES"
    [ -n "${AC_BUDGET_NOTES:-}" ] && printf 'Budget: %s. Stay inside it; if the study cannot, make it smaller now.
' "$AC_BUDGET_NOTES"
    printf '=== END ===

'
  fi
  local want=""
  case "$base" in
    1) want="direction experiments" ;;
    2|3|4|5|6) want="experiments" ;;
    11|13) want="writing" ;;
  esac
  for f in $want; do
    [ -s "$ROOT/state/strategy/$f.md" ] || continue
    printf '=== YOUR STRATEGY: %s (state/strategy/%s.md, from past reviews) ===
' "$f" "$f"
    head -c 6000 "$ROOT/state/strategy/$f.md"
    printf '
=== END ===

'
  done
  # The owner's answers to its questions, given on the website (KIT-009):
  # the latest of them, before their standing instructions.
  if [ -s "$ROOT/state/answers.md" ]; then
    printf '=== YOUR OWNER'"'"'S ANSWERS TO YOUR QUESTIONS (state/answers.md) ===\n'
    tail -c 6000 "$ROOT/state/answers.md"
    printf '\n=== END ===\n\n'
  fi
  # custom/website.md: what the owner wrote on the agent's page on the
  # website (KIT-008), kept there by client.py sync.
  for f in "$ROOT/custom/all.md" "$ROOT/custom/website.md" "$ROOT/custom/step-$base.md" "$ROOT/custom/step-$n.md"; do
    [ -s "$f" ] || continue
    printf '=== YOUR OWNER'"'"'S INSTRUCTIONS (%s) ===
' "${f#$ROOT/}"
    head -c 6000 "$f"
    printf '
=== END ===

'
  done
}
# A step's time limit guards against a turn that hangs; it is not a budget. A
# model this machine serves (an Ollama, LM Studio, llama.cpp or vLLM provider)
# is slower, so its steps get three times as long; AC_STEP_TIMEOUT_SCALE, a
# whole number, sets the factor for any model.
step_timeout() {
  local s=${AC_STEP_TIMEOUT_SCALE:-}
  case "$s" in ''|*[!0-9]*|0)
    case "${AC_MODEL:-}" in ollama/*|lmstudio/*|llama.cpp/*|llamacpp/*|vllm/*|local/*) s=3 ;; *) s=1 ;; esac ;;
  esac
  echo $(( $1 * s ))
}
# Every research step is ONE headless turn (`claude -p`, `codex exec`, …): when
# the model stops, nothing re-invokes it. A model used to interactive sessions
# will otherwise start a long job in the background, schedule itself a wake-up
# and end the turn -- the next step's gate then finds no output and stops the
# paper, with the job still running unobserved (a live test, 2026-09-29: step
# 4's calibration). Said once, in front of every step.
turn_note() {
  printf '=== THIS TURN ===\nThis step is one turn of a coding agent run from a script. When you finish, nothing re-invokes you: no wake-ups, no notifications, no later check-in. Run what the step needs to completion inside this turn -- a long job in the foreground, or started and then waited for until it ends. Never end the turn while a process you started is still running, and never schedule a wake-up: the next step starts the moment you stop, and it checks this step'"'"'s outputs. Other agents may be running on this machine: stop only processes you started, by their process id -- never pkill or killall by name or pattern -- and keep logs and temporary files in this directory, not in /tmp.\nNobody answers questions during this turn. Where a skill says to ask the user or wait for a confirmation, decide as a careful researcher would, from the plan, these files and your owner'"'"'s instructions below; write the decision and why in refine-logs/DECISIONS.md and go on. Stop only for what this machine cannot do or a rule you cannot keep, and then say exactly what is needed.\n=== END THIS TURN ===\n\n'
}
# A step trying again after it failed (run-heartbeat.sh) is told what went
# wrong the last time, ahead of everything else.
retry_note() {
  local n base f
  n=${1%%/*}; base=$(printf '%s' "$n" | tr -dc '0-9')
  f="$W/refine-logs/RETRY-step-$base.md"
  [ -n "$base" ] && [ -s "$f" ] || return 0
  printf '=== THE LAST ATTEMPT AT THIS STEP FAILED (refine-logs/RETRY-step-%s.md) ===\n' "$base"
  tail -c 6000 "$f"
  printf '\n=== END ===\nRead that first: fix what went wrong, or reach the step'"'"'s goal another way that cannot fail like that. A step that ran out of time did too much in one go: do less in it, or split the work. Never lower a check'"'"'s bar, or change a check, to get past it.\n\n'
}
# A step the model's limit cut off (run-heartbeat.sh, pipeline/resume.py) is
# told so, and what the cut-off attempt left on disk, so it resumes rather than
# redoes: run again from the top unprompted, an experiment step rewrote results
# it had already finished (a tester's report, 2026-10-05).
resume_note() {
  local n base f
  n=${1%%/*}; base=$(printf '%s' "$n" | tr -dc '0-9')
  f="$W/refine-logs/RESUME-step-$base.md"
  [ -n "$base" ] && [ -s "$f" ] || return 0
  printf '=== THIS STEP WAS INTERRUPTED, NOT FAILED (refine-logs/RESUME-step-%s.md) ===\n' "$base"
  head -c 6000 "$f"
  printf '\n=== END ===\n\n'
}
# skill <label> <prompt> [timeout] [fresh]. A fresh turn -- step 13's attack
# and its judging -- is given the paper and its evidence and nothing of the
# author's side: not the owner's instructions or answers, not the strategy, not
# what earlier attempts said. Those are the author's case, and a turn told it
# first attacks the paper softly (a tester's report, 2026-10-05).
skill(){ local label=$1 prompt=$2 tmo
         tmo=$(step_timeout "${3:-7200}")
         if [ "${4:-}" = fresh ]; then
           prompt="$(turn_note)$prompt"
         else
           prompt="$(turn_note)$(resume_note "$label")$(retry_note "$label")$(deadline_note)$(owner_context "$label")$prompt"
         fi
         if [ -n "$DRY" ]; then
           printf '\n\033[1m===== %s =====\033[0m\n%s\n' "$label" "$prompt"
           printf '\033[2m[%s chars]\033[0m\n' "$(printf '%s' "$prompt" | wc -c)"
           return 0
         fi
         say "$label"
         # What the model was asked, kept for the heartbeat's turn record.
         printf '=== %s ===\n%s\n\n' "$label" "$prompt" >> "$W/.step-prompts"
         # --foreground: GNU timeout otherwise moves the command into a process
         # group of its own, where stopping the loop (which signals the
         # pipeline's group) cannot reach the agent CLI or what it started.
         # The owner's GPUs, and only those (A21). Unset: whatever the machine has.
         case "${AC_GPUS:-}" in ''|none|NONE) ;; *) export CUDA_VISIBLE_DEVICES="$AC_GPUS" ;; esac
         [ "${AC_GPUS:-}" = none ] && export CUDA_VISIBLE_DEVICES=""
         # The instruction goes on stdin, never on a command line (agent-turn.sh).
         timeout --foreground "$tmo" "$ROOT/pipeline/agent-turn.sh" --mode research --dir "$W" - \
             <<<"$prompt" 2>&1 | tee -a "$LOG"
         local rc=${PIPESTATUS[0]}
         [ "$rc" -eq 0 ] || { echo "research: step failed (exit $rc)" >&2; return "$rc"; }; }
# The research side's hand-off to the writer: every aggregate and the verdict.
evidence_digest() {
  ( cd "$W" && for f in readiness.json runs/aggregate__*.json; do
      [ -f "$f" ] && printf '%s  %s\n' "$(python3 -c 'import hashlib,sys;print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' "$f")" "$f"
    done )
}
verify_evidence() {
  [ -f "$W/.evidence.sha" ] || return 0
  if [ "$(evidence_digest)" != "$(cat "$W/.evidence.sha")" ]; then
    echo "research: the evidence changed $1 -- readiness.json or an aggregate was edited" >&2
    echo "  by the writing side, which evidence-interface.md forbids. Re-run step 11." >&2
    return 1
  fi
}
want() { if [ -n "$STEP" ]; then [ "$STEP" = "$1" ]; else
           [ "$1" -ge "$FROM" ] && [ "$1" -le "$TO" ]; fi; }
# Re-running anything the paper was written from invalidates the finished
# paper (step 11 reads the mark).
if [ -z "$DRY" ]; then
  for n in 1 2 3 4 5 6 7 8 9 10; do want "$n" && { rm -f "$W/.paper-ready"; break; }; done
  # A resume note belongs to the pass its step was cut off in (pipeline/
  # resume.py): running an earlier step -- the loop going back, or the owner
  # moving pipeline.next -- starts a new pass, and the later steps' notes go.
  python3 "$ROOT/pipeline/resume.py" forget "$W" $(( ${STEP:-$FROM} + 1 )) >/dev/null 2>&1
fi
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
'modest but sufficient', and every number in it carries the reason it is that
number. Its _kinds note says which sections bind which kind of study, and its
models section names the models of the study this pipeline was first built
for: an example of the shape, not models any study must use -- a study need not
involve language models at all. For every kind: every reported number comes with its interval (an exact computation
excepted), at least \$(jq -r .statistics.instance_seeds $QUALITY) seeds that
redraw what actually varies, a trivial baseline that sets the floor, and an
ablation per claim. If the study measures what language models generate, these
bind as well: at least \$(jq -r .statistics.min_n_per_cell $QUALITY)
samples per (model, condition, level) cell, \$(jq -r .statistics.instance_seeds $QUALITY)
instance seeds (a seed must redraw the INSTANCES — decoding is greedy, so a torch
seed changes nothing and reporting it as a spread would be fabricated), at least
\$(jq -r .models.min_count $QUALITY) models, at least
\$(jq -r .design.min_complexity_levels $QUALITY) complexity levels, and at most
\$(jq -r .token_budget.max_truncation_rate_per_cell $QUALITY) of any cell truncated."
QBAR=$(eval "printf '%s' \"$QBAR\"")

# No reviewer backend on this machine, and no person to ask (a live user,
# 2026-10-04: "every so often a manual-review page opens"). `— reviewer:
# manual` is what keeps ARIS off Codex MCP, which cannot be installed here --
# but it routes every review to a manual-review MCP server that opens a
# browser page for a person to paste the prompt into another model, and a
# research turn, with every permission, once installed that server itself.
# Of the directives ARIS offers (codex, oracle-pro, agy, manual) none
# degrades to the executor: each names a backend, the first three fall back
# to Codex, and manual stops when its server is missing. So the directive
# stays, the server's tools are kept out of reach (agent-turn.sh), and every
# step that passes it is told this, in the same words:
NO_REVIEWER=$(cat <<'TXT'
There is no external reviewer on this machine and no person to ask. Where
the skill routes a review to a reviewer backend (Codex MCP, Oracle, the agy or
manual-review MCP), or says a reviewer MCP is not installed and to stop: do
not stop, and do not install anything. Do that review yourself, as a separate,
adversarial pass over the artifact, say in its report that it is a self-review
by the executor (never cross-model acceptance), and continue the skill. Never
install, add or configure an MCP server, a plugin or a CLI setting (no `claude
mcp add`, nothing under ~/.claude, ~/.codex or ~/.config), never open a
browser, and never wait for a person.
TXT
)

say "workspace $W   (paper=${PAPER:-none} backend=$("$ROOT/pipeline/agent-turn.sh" --which 2>/dev/null || echo none) kind=${KIND:-undecided} pilot=${AC_PILOT:-0})"

# ── 1 ─ ARIS: paper -> ideas -> plan ─────────────────────────────────────────
# `ref paper` is ARIS's own parameter for "use this paper as context, do not
# reproduce it". effort raised from lite to balanced and assurance pinned to
# submission: ARIS maps lite -> draft, under which audits may silently skip, and
# a silently skipped audit is how the first run shipped without a single equation.
if want 1; then
  skill "1/15 idea-discovery (ARIS)" \
"/idea-discovery \"${DIRECTION:-the direction implied by the reference paper}\"${PAPER:+ — ref paper: $PAPER} — reviewer: manual — effort: balanced — assurance: submission — auto proceed: true — render html: false

$NO_REVIEWER

$QBAR

Hardware, measured, in $MACHINE: read it before proposing anything. What it
says will not fit does not fit. Cost every pilot against the throughput
measured there, not against a normal box. If it lists no GPU, propose theory
whose claims small CPU computations can check, or an experiment that runs on
CPU well inside the budget — nothing that needs a GPU.

Stay inside the research direction above: it is the owner's, and a study
outside it can be desk-rejected. Use language models only if the direction is
about them.

Choose a question worth answering (A21). Before committing to one, write in
refine-logs/FINAL_PROPOSAL.md, in two sentences each: who would change what
they do if the answer came out either way, and why this is not already known.
A question whose answer changes nothing, or that a baseline everyone runs
already settles, is not worth this cycle. Then size the study to the compute
you were given: the GPUs listed above are there to be used, and reviewers
have called agents' experiments basic when a toy stood in for a study the
machine could have run.

If refine-logs/NO_GO_HISTORY.md exists, earlier plans for this paper were judged
infeasible on this machine, for the reasons recorded there. Propose something
that fits; a smaller copy of a rejected plan is still that plan.

Finish with idea-discovery's own outputs on disk -- refine-logs/FINAL_PROPOSAL.md
and refine-logs/EXPERIMENT_PLAN.md -- because every later step reads them.

The reference paper, if there is one, is an inspiration source. Do not propose reproducing it, and
do not propose re-scoring its benchmark — propose work it suggests.

An idea only survives if it can carry a paper with a FORMAL method: something
with notation and equations, not a procedure described only in prose. If the best
idea you have cannot be written down mathematically, it is the wrong idea for
this venue." || exit 1
  if [ -z "$DRY" ]; then
    for f in refine-logs/FINAL_PROPOSAL.md refine-logs/EXPERIMENT_PLAN.md; do
      [ -s "$W/$f" ] || { echo "research: step 1 left no $f; every later step reads it." >&2; exit 1; }
    done
  fi
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
  if [ -z "$DRY" ]; then
    KIND=$(jq -r '.study_kind // empty' "$(dirname "$PLAN")/FEASIBILITY.json" 2>/dev/null)
    case "$KIND" in llm-generation|computational|theory) ;; *)
      echo "research: FEASIBILITY.json names no study_kind" >&2; exit 3 ;; esac
    printf '%s\n' "$KIND" > "$W/STUDY_KIND"
    say "study kind: $KIND"
  fi
fi

# ── 4 ─ the fix for the failure that ruined the first run ───────────────────
# A generation cap is a measurement instrument. Calibrate it against the task,
# then refuse to proceed if it is too small. Cheap: a handful of generations.
if want 4; then need_kind; fi
if want 4 && [ "$KIND" != llm-generation ]; then
  say "4/15 token-budget calibration: not a $KIND study's instrument; skipped"
elif want 4; then
  skill "4/15 calibrate the token budget (ARIS experiment-bridge, calibration only)" \
"/experiment-bridge refine-logs/EXPERIMENT_PLAN.md — gpu: local — reviewer: manual — effort: lite

$NO_REVIEWER

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
  need_kind
  if [ "$KIND" = llm-generation ]; then
    S5_HEAD="Run the FULL sweep from the plan, using the caps in runs/CALIBRATION.json — one
cap per model, as calibrated. Do not fall back to a smaller cap to save time; if
the budget is tight, cut a cell, and record in runs/manifest.json's \`notes\`
exactly what you cut. A truncated sweep reported as a complete one is the thing
peer review exists to catch."
    S5_HW="Hardware rules, not suggestions:
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
    slowdown while looking fine in GPU memory."
    S5_AUDIT="Rules that keep it auditable, because a reviewer will check every one:
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
  * A script that looks for files -- checkpoints, data, outputs -- names the
    directories it means. Never walk the whole workspace by file extension: it
    holds your virtual environment and tool caches, whose files share those
    extensions (a setuptools \`.pth\` in .venv is not a model)."
    GPU_LIST=${AC_GPUS:-0}; case "$GPU_LIST" in none|NONE) GPU_LIST="" ;; esac
    S5_ENV="\"CUDA_VISIBLE_DEVICES\": \"$GPU_LIST\", \"HF_HOME\": \"$HFH\""
    S5_TAIL="Greedy decoding on fixed instance seeds reproduces here, so accuracy-like
fields belong in \`exact\`; wall-clock time and throughput go in \`timing\`."
  else
    if [ "$KIND" = theory ]; then
      S5_HEAD="This study's contribution is its derivations. The experiments are the numerical
checks the plan names: small computations that test each derived claim on
concrete instances, where it could come out wrong. Run every one. If the budget
is tight, cut a check, and record in runs/manifest.json's \`notes\` exactly what
you cut and which claim it leaves unchecked."
    else
      S5_HEAD="Run the FULL set of experiments from the plan. If the budget is tight, cut a
cell, and record in runs/manifest.json's \`notes\` exactly what you cut. A
partial run reported as a complete one is the thing peer review exists to catch."
    fi
    S5_HW="Hardware rules, not suggestions — size everything against $MACHINE:
  * With a GPU there: one model resident at a time, freed between loads; the
    largest batch that fits; no host-side accumulation per step that would force
    batch 1.
  * Without one: everything runs on CPU. Estimate the wall-clock before you
    start and stay inside the budget.
  * No more process-pool or dataloader workers than the cores it lists.
  * export HF_HOME=$HFH if anything downloads models or datasets."
    S5_AUDIT="Rules that keep it auditable, because a reviewer will check every one:
  * Never score a method by its own report of how it did. Re-derive every metric
    from the raw output with code you wrote.
  * Keep the RAW output behind every number, so any number can be checked.
  * Every record carries the configuration, condition and seed that produced it.
  * Fix every seed and record it; the spread you report comes from seeds you
    name, never from uncontrolled randomness.
  * A script that looks for files -- checkpoints, data, outputs -- names the
    directories it means. Never walk the whole workspace by file extension: it
    holds your virtual environment and tool caches, whose files share those
    extensions (a setuptools \`.pth\` in .venv is not a model)."
    S5_ENV=""
    S5_TAIL="A computation with fixed seeds reproduces, so its outputs belong in
\`exact\` (a float is compared to floating-point precision, so a process pool
summing in another order is fine). A result that really varies from run to run
-- a nondeterministic GPU kernel, thread timing -- goes in \`tolerant\` with the
band you saw across two runs; wall-clock time and throughput go in \`timing\`."
  fi
  skill "5/15 experiment-bridge (ARIS)" \
"/experiment-bridge refine-logs/EXPERIMENT_PLAN.md — gpu: local — reviewer: manual — effort: balanced

$NO_REVIEWER

$S5_HEAD

$QBAR

$S5_HW

$S5_AUDIT

Write results as JSON under runs/results/.

Then write runs/REPLAY_MANIFEST.json — note the name; it is the REPLAY contract and
is separate from any run-provenance manifest you may also want to write:

  {\"env\": {$S5_ENV},
   \"notes\": \"anything you cut from the plan, and why\",
   \"experiments\": [{\"script\": \"<path, relative to runs/ or to the workspace>\",
                     \"output\": \"<results file it writes, relative to runs/>\",
                     \"args\": [], \"timeout_s\": 7200,
                     \"exact\": [\"field names that must come out the same\"],
                     \"tolerant\": {\"<a field that varies run to run>\": 0.05},
                     \"timing\": [\"wall_s\"]}]}

Every leaf number in your results must be named in \`exact\`, \`tolerant\` or
\`timing\`. research/scripts/check_reproduction.py re-runs each script from a
clean copy and FAILS on any number that is in none of them, because an
unclassified number is one nobody decided was reproducible. \`timing\` fields
measure the machine, so they are re-measured and never compared; report them in
the paper as approximate, with the hardware. $S5_TAIL$PILOT" 25200 || exit 1
fi

# ── 6 ─ ARIS: statistics, then what the numbers support ─────────────────────
if want 6; then
  need_kind
  if [ "$KIND" = llm-generation ]; then
    S6_STATS="Compute a $(jq -r .statistics.ci_method "$QUALITY") interval for every accuracy —
the normal approximation is invalid here because every rate sits near zero and n
is small. Report the interval, not just the point estimate, and report spread
across the instance seeds.

Write runs/results/summary.json with, per cell: model, condition, level, n,
correct, accuracy, ci_low, ci_high, truncation_rate. Step 7 plots this file and
step 12 counts it."
  else
    S6_STATS="Compute an interval for every reported number: $(jq -r .statistics.ci_method "$QUALITY")
for a proportion, a t or bootstrap interval for a mean over seeds. A number that
is an exact computation needs none; say that it is exact. Report the interval,
not just the point estimate, and report the spread across seeds.

Write runs/results/summary.json with, per compared configuration and condition:
configuration, condition, n, value, ci_low, ci_high (null when exact), exact
(true or false). Step 7 plots this file and step 11 reads it."
  fi
  skill "6/15 analyze-results + result-to-claim (ARIS)" \
"/analyze-results runs/results/ — effort: balanced

$S6_STATS

Then run /result-to-claim to say which claims these numbers support and which
they do not. A claim whose interval contains the baseline is not supported —
say so. A well-measured null result is publishable at this venue and is
explicitly in scope; a claim dressed up beyond its interval is not.$PILOT" || exit 1
fi

# ── 7 ─ ARIS: real figures, on disk ─────────────────────────────────────────
if want 7; then
  need_kind
  if [ "$KIND" = llm-generation ]; then
    S7_FIG="minimum a results figure showing accuracy against complexity, one series per
(model, condition), with the $(jq -r .statistics.ci_method "$QUALITY") intervals
drawn as error bars."
  else
    S7_FIG="minimum a results figure for the headline comparison, one series per
configuration, with its intervals drawn as error bars where it has them."
  fi
  skill "7/15 paper-figure (ARIS)" \
"/paper-figure runs/results/summary.json — effort: balanced

Produce real figure FILES under figures/ — not descriptions of figures. At
$S7_FIG If a cell is empty because everything in it truncated, show
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
# Then checked, not taken on the turn's word (a tester's report, 2026-10-05: a
# turn that wrote no related work at all passed): research/scripts/
# check_related_work.py looks every work up and wants the stated differences.
# When the reference services did not answer for enough of the list, the next
# try checks the same list again rather than writing a new one.
related_work_waiting() {
  python3 - "$W/refine-logs/RELATED_WORK.check.json" "$W/refine-logs/RELATED_WORK.json" <<'WAIT' 2>/dev/null
import hashlib, json, sys
c = json.load(open(sys.argv[1]))
sys.exit(0 if c.get("outcome") == "unchecked" and
         c.get("sha256") == hashlib.sha256(open(sys.argv[2], "rb").read()).hexdigest() else 1)
WAIT
}
if want 9; then
  if [ -z "$DRY" ] && related_work_waiting; then
    say "9/15 the related work of the last try is unchanged and waited only on the reference services; checking it again"
  else
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
prior work this contradicts, and prior work that solves a neighbouring problem.

Write the same list as refine-logs/RELATED_WORK.json, for the check after this step:

  {\"works\": [{\"title\": \"...\", \"arxiv_id\": \"2307.03172\" or null, \"doi\": \"10.…\" or null,
              \"relation\": \"builds_on\" | \"contradicts\" | \"neighbouring\",
              \"what_it_does\": \"...\",
              \"difference\": \"how it differs from what this paper claims\"}]}

python3 $ROOT/research/scripts/check_related_work.py . looks every work up --
an arXiv id on arXiv, a DOI on Crossref, a title alone on Semantic Scholar --
and fails this step for a work that does not exist, an identifier that names a
different paper than its title, a difference of fewer than twelve words or
copied from another work's, or fewer than $(jq -r .paper_shape.min_citations "$QUALITY")
works. Run it before you finish, and fix what it reports." || exit 1
  fi
  gated "9b/15 related-work check (ours)" python3 "$ROOT/research/scripts/check_related_work.py" "$W" || {
    echo "research: the related work does not hold (above): step 9 again." >&2; exit 1; }
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
  need_kind
  # A re-run of step 11 after the paper already passed its gates -- say the
  # render failed on a construct it did not know -- goes straight to the
  # render. Rewriting a finished paper is an hour of model time for nothing,
  # and a different paper. Only while the evidence is the one it was written
  # from; any step up to 10 withdraws the mark.
  if [ -z "$DRY" ] && [ -f "$W/.paper-ready" ] && [ -f "$W/.evidence.sha" ] \
     && [ "$(evidence_digest)" = "$(cat "$W/.evidence.sha")" ]; then
    say "11a-b/15 the paper passed its gates on this evidence already; rendering it again"
  else
  rm -f "$W/.paper-ready"
  skill "11a/15 hand the evidence to the writer (research side)" \
"Hand this study's evidence to the writing skill. You are the research side of
$ROOT/interfaces/evidence-interface.md; read it, then the section \"Handing off
to the writing skill\" in $ROOT/research/SKILL.md, and produce exactly the two
things it names, in this workspace:

  1. runs/aggregate__<method>.json — one per compared configuration (each model
     x condition the plan compares, and each ablated variant), from the raw
     results under runs/results/ and runs/*.jsonl. per_split is keyed by the
     plan's condition (for a language-model study, its complexity level);
     values are the per-seed results, raw;
     state the estimator. Carry each cell's interval from runs/results/summary.json
     as ci_low / ci_high beside its mean (null for an exact computation). primary_inputs lists the files each
     aggregate reads, and every one must exist on disk.
  2. readiness.json — READY or BLOCKED, one claim per intended headline claim.

The writer may print only numbers these files carry, and step 14 checks every
number the paper prints against the files under runs/. So store, computed here
and not left to the writer: every interval the paper will show, as ci_low /
ci_high (a paired contrast's too, not only its uncertainty), and the design's
own parameters the paper will state (noise orders, horizons, sample sizes) in
runs/DESIGN.json.

If refine-logs/UNTRACEABLE.md exists, the last paper printed the numbers listed
there and no file under runs/ carried them. Add the ones that are legitimate
results or parameters, computed from the raw results; the rest the writer will
drop.

Decide 'supported' the way step 6 was told to: a claim whose
$(jq -r .statistics.ci_method "$QUALITY") interval contains the baseline is not
supported. Use CLAIMS_FROM_RESULTS.md where it adjudicated a claim; where it
stopped (for example REVIEW_UNAVAILABLE), read the intervals yourself and say in
the claim's notes that this was a reading of the intervals, not a second model's
review. An unsupported claim is still a result — a well-measured null is in
scope at this venue — so it goes in the verdict as supported: false; it does
not block.

BLOCKED only when the evidence cannot carry a paper at all: the experiments did
not reproduce -- runs/REPRO_GATE.json missing, or any entry in its \"experiments\"
list not PASS -- or no cell has a measured interval. Then fill blocked_on. An
\"experiments\" entry whose script is \"(paper)\" is not a reproduction result: it
is step 14's verdict on an earlier draft's printed numbers, which is what a
rewrite fixes, and it does not block.

You may not write LaTeX, touch the paper, or phrase a result for it. Do not run
new experiments and do not edit anything under runs/results/." 3600 || exit 1

  # The hand-off is frozen here. The writer runs with its approvals off in the
  # same workspace, so the interface's rule that the writing side may not edit
  # an aggregate or relax a verdict is checked, not trusted.
  [ -n "$DRY" ] || evidence_digest > "$W/.evidence.sha"

  # The design family can draw a paper with no display equations; this
  # pipeline cannot use one -- step 8 derives a formalism for the method
  # section and step 12 wants display equations. So the equation register is
  # drawn here, from the two that always carry displays, by the same seed.
  DSEED=$(printf '%s' "$SLUG$(basename "$W")" | cksum | cut -d' ' -f1)
  EQREG=moderate; [ $((DSEED % 2)) -eq 1 ] && EQREG=dense
  skill "11b/15 write the paper (paper-writing)" \
"Write this study's paper with the paper-writing skill at $ROOT/paper-writing.
Read $ROOT/paper-writing/SKILL.md and follow its workflow from step 1. This
workspace is the project root: runs/aggregate__*.json and readiness.json are the
evidence; nothing else may fill a slot.

Set up with:
  python3 $ROOT/paper-writing/scripts/design_paper.py --seed $DSEED --layout draw --evidence runs/ --prefer equations=$EQREG
Its gates are <skill>/scripts/gate.sh with <skill> = $ROOT/paper-writing.

What the study is, for the writing: refine-logs/FINAL_PROPOSAL.md and
refine-logs/EXPERIMENT_PLAN.md (the method and the design), refine-logs/FORMALISM.md
(carry its notation and equations into the method section),
refine-logs/RELATED_WORK.md (its references are verified; take their BibTeX from
arXiv or Crossref, never from memory), idea-stage/REF_PAPER_SUMMARY.md (the
inspiring paper, when the study had one — cite it as inspiration, do not claim
to have reproduced it),
runs/REPRO_GATE.json (what reproduced). figures/ holds step 7's plots; your
figures come from paper/data, generated from the aggregates, as the skill says.

Print only numbers an aggregate or a file under runs/ carries, rounded as you
like: never compute a new one in the paper -- an interval endpoint, a
difference, a ratio. Step 14 fails the paper for each number it cannot trace.
If refine-logs/UNTRACEABLE.md exists, the previous draft printed the numbers
listed there without a source; each must now come from a file, or go. If
refine-logs/SHAPE_FAILURES.md exists, the previous draft failed the platform
shape checks listed there; this one must pass them. If refine-logs/PAGE_BUDGET.md
exists, the platform refused the previous render as too long; it says by how
much, and this draft's main text must fit.

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

The venue is double-blind until publication. Nothing in the paper,
REPRODUCIBILITY.md or keywords may identify the authors or this machine: no
names, affiliations, acknowledgments or funding (delete the template's
Acknowledgments block rather than filling it), no usernames, hostnames or
absolute paths (write ~/.cache/huggingface, not the full path).

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
  [ -n "$DRY" ] || verify_evidence "after the writer" || exit 5
  gated "11b/15 readiness verdict (ours)" python3 -c '
import json, sys
v = json.load(open(sys.argv[1])).get("verdict")
print("readiness:", v)
sys.exit(0 if v == "READY" else 1)' "$W/readiness.json" || {
    echo "research: readiness.json is not READY; see its blocked_on (steps 4-6)." >&2; exit 5; }
  # Only a READY paper is marked. In pilot mode the gates above do not stop the
  # step, and marking a BLOCKED paper sent every retry straight to a render that
  # refuses it: in a live test the owner's "retry step 11" changed nothing.
  if [ -z "$DRY" ] && python3 -c 'import json,sys; sys.exit(0 if json.load(open(sys.argv[1])).get("verdict") == "READY" else 1)' "$W/readiness.json" 2>/dev/null; then
    touch "$W/.paper-ready"
  fi
  fi

  if [ -n "$DRY" ]; then
    printf '\n\033[1m===== %s =====\033[0m\n  $ %s\n' "11c/15 render for the platform (ours)" \
      "make_submission.py $W --out $W/.submission-build -> $W/submission.json + figures/"
  else
    run "11c/15 render for the platform (ours)" \
      python3 "$ROOT/submission/scripts/make_submission.py" "$W" --out "$W/.submission-build" || {
      # Too long by the platform's own rule: step 11 again must rewrite it
      # shorter, not render the same text -- so the mark goes, and the writer is
      # told by how much.
      if python3 - "$W/.submission-build/page_count.json" "$W/refine-logs/PAGE_BUDGET.md" <<'PAGES' 2>/dev/null; then
import json, sys
pc = json.load(open(sys.argv[1]))
if not pc.get("over"):
    sys.exit(1)
open(sys.argv[2], "w").write(
    f"# The platform refused the last render as too long\n\n"
    f"Its main text is {pc['pages']} pages by the platform's rule against a limit of {pc['limit']:g} "
    f"({pc['words']} words, {pc['figures']} figures, {pc['tables']} tables). Cut about {pc['cut_words']} words "
    f"from the main text, or move material after the Appendix heading: nothing from the first "
    f"References or Appendix heading on is counted. The rule: 700 words = 1 page; each figure 0.3; "
    f"each table 0.1 plus 0.02 per row; each line of code 0.02; each displayed equation 0.04.\n")
PAGES
        rm -f "$W/.paper-ready"
        echo "research: the main text is too long for the platform (refine-logs/PAGE_BUDGET.md); step 11 again rewrites it shorter." >&2
      fi
      exit 5; }
    rm -f "$W/refine-logs/PAGE_BUDGET.md"
    # figures/ must hold exactly the paper's figures: step 15 attaches every PNG
    # in it and insert_figures appends any the text does not place. Step 7's
    # plots are kept beside it, not deleted.
    # Only the first time: on a re-run, figures/ holds the previous render and
    # step 7's plots are already set aside.
    if [ ! -d "$W/figures-step7" ] && [ -n "$(ls -A "$W/figures" 2>/dev/null)" ]; then
      mv "$W/figures" "$W/figures-step7"
    fi
    rm -rf "$W/figures"; mkdir -p "$W/figures"
    cp "$W/.submission-build/figures/"* "$W/figures/" 2>/dev/null || true
    cp "$W/.submission-build/submission.json" "$W/submission.json"
    # A new rendering is a new paper to attack: step 13's attack on the last
    # one, and the answers to it, go.
    rm -rf "$W/.kill-argument" "$W/KILL_ARGUMENT.json" "$W/KILL_ARGUMENT.md" "$W/refine-logs/KILL_ARGUMENT_ANSWERS.md"
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
# Three turns, so that what judges the paper never heard the author's side (a
# tester's report, 2026-10-05: one turn attacked, fixed and graded the paper
# after reading the owner's strategy and instructions, and the pipeline went on
# whatever KILL_ARGUMENT.json said, or if it said nothing readable):
#   13a  the attack, judged against the paper as it stands   fresh (skill ... fresh)
#   13b  the author answers what stands                      the owner's context, as every step
#   13c  the answered paper judged again, point by point     fresh, held to 13a's points
# research/scripts/check_kill_argument.py computes the verdict from the points
# (the skill's own table), never from the verdict the file states. A critical
# point still standing after 13c stops the paper (exit 6, tried again: 13b
# answers the same points, told what stood); a file it cannot use is a failed
# step (exit 1). The attack on this rendering is kept in .kill-argument/ across
# tries, so a second try answers it rather than starting a new one; step 11's
# render withdraws it. A judging turn may not edit the paper: it is compared
# before and after, and put back.
KCHECK="$ROOT/research/scripts/check_kill_argument.py"
KA="$W/KILL_ARGUMENT.json"
KDIR="$W/.kill-argument"
paper_sha() { python3 -c 'import hashlib,sys;print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' "$W/submission.json" 2>/dev/null; }
ka_usable() { python3 "$KCHECK" "$@" >/dev/null 2>&1; [ $? -lt 3 ]; }
judge() {   # judge <label> <prompt>: a fresh turn that leaves the paper as it found it
  local label=$1 before
  [ -n "$DRY" ] || { before=$(paper_sha); cp "$W/submission.json" "$KDIR/paper-before.json"; }
  skill "$label" "$2" 3600 fresh || return 1
  [ -n "$DRY" ] && return 0
  if [ "$(paper_sha)" != "$before" ]; then
    # Its rulings were made on a paper that is no longer there: they go too.
    cp "$KDIR/paper-before.json" "$W/submission.json"
    rm -f "$KA"
    echo "research: $label edited submission.json, which a judging turn may not do; the paper is put back as it was." >&2
    return 1
  fi
}
if want 13; then
  mkdir -p "$KDIR"
  if [ -z "$DRY" ] && ka_usable "$KDIR/attack.json"; then
    say "13a/15 this rendering was attacked on an earlier try (.kill-argument/attack.json); answering that attack"
    ka_usable "$KA" --held-to "$KDIR/attack.json" || cp "$KDIR/attack.json" "$KA"
  else
    rm -f "$KA" "$W/KILL_ARGUMENT.md" "$KDIR/attack.json"
    judge "13a/15 kill-argument: the attack (ARIS)" \
"/kill-argument submission.json — reviewer: manual — effort: balanced — render html: false

$NO_REVIEWER

You are a hostile reviewer meeting this paper for the first time. This turn is
the attack and its judging, and nothing else: the author answers in the next
turn, and a fresh reader judges the answered paper after that.

Read the paper (submission.json) and what it rests on: runs/ (the results and
the code that made them), readiness.json, runs/REPRO_GATE.json and the works it
cites. Nothing of the author's side is in this turn, on purpose -- no notes, no
strategy, no instructions -- so do not look for it: leave refine-logs/ unread.
Do not edit submission.json, the paper or anything under runs/; the pipeline
compares submission.json before and after this turn.

The cross-model reviewer this skill prefers needs Codex MCP, which cannot be
installed here -- so this is a same-family review and must record itself as
such. Do not label it cross-model acceptance.

Write the single strongest argument for rejecting this paper, about 200 words.
Then break it into 3 to 7 atomic rejection points and judge each against the
paper as it stands: answered_by_current_text, partially_answered or
still_unresolved, with its severity if unresolved (critical, major or minor)
and one recommended fix. Attack what a real reviewer will: does each interval
support its claim, or contain the baseline? Is the effect larger than the
spread across seeds? Does the method's formal definition match what the code
did? Is a load-bearing citation unverified? Does the title or abstract claim
more than the body shows? This pipeline attacks every paper, empirical or
theoretical: NOT_APPLICABLE is not a verdict here.

Write KILL_ARGUMENT.md and KILL_ARGUMENT.json in this directory, the JSON in the
skill's schema. The pipeline reads details.attack_memo and
details.decomposed_points -- each with id, attack_claim, verdict,
severity_if_unresolved and recommended_fix -- and computes the verdict from the
points itself: a file it cannot read stops this step." || exit 1
    if [ -z "$DRY" ]; then
      if ka_usable "$KA"; then
        cp "$KA" "$KDIR/attack.json"
      else
        python3 "$KCHECK" "$KA"
        echo "research: the attack left no KILL_ARGUMENT.json the pipeline can use (above)." >&2
        [ "$BLOCKING" = 1 ] && exit 1
        say "^^ not blocking (pilot mode): the attack's answer and judging are skipped"
      fi
    fi
  fi
  # Where the paper stands: 0 PASS, 1 WARN, 2 FAIL, 3 no usable verdict.
  KV=0
  if [ -z "$DRY" ]; then
    if [ -s "$KDIR/attack.json" ]; then
      run "13a/15 what stands against it (ours)" python3 "$KCHECK" "$KA" --held-to "$KDIR/attack.json"
      KV=$?
    else
      KV=3
    fi
  fi
  if [ -n "$DRY" ] || [ "$KV" -eq 1 ] || [ "$KV" -eq 2 ]; then
    skill "13b/15 answer the attack (the author)" \
"Answer the attack on this paper. KILL_ARGUMENT.json in this directory holds a
hostile reviewer's case against it (details.attack_memo), broken into points
(details.decomposed_points), each judged against the paper as it stood. After
you, a fresh reader judges every point again, from the paper alone.

In submission.json, answer every point that is still_unresolved, and every one
partially_answered at critical or major severity:
  * It lands and the text can fix it -- a claim worded beyond its interval, a
    missing qualification, an unclear definition, a comparison the results
    already hold: fix it.
  * It lands and cannot be fixed at this scale: state it precisely in the
    limitations, and narrow the claim it undermines -- not a blanket
    disclaimer.
  * It does not land: make the paper show why, where a reader would look.

Print only numbers a file under runs/ carries: step 14 checks every one. Do not
run new experiments, and do not edit anything under runs/, readiness.json, the
aggregates, KILL_ARGUMENT.json or KILL_ARGUMENT.md.

The platform refuses a main text over its page budget. After your changes run
python3 $ROOT/submission/scripts/page_count.py submission.json; if it says
\"over\", cut or move material past the Appendix heading until it does not.

Write refine-logs/KILL_ARGUMENT_ANSWERS.md: per point id, what you changed and
where." || exit 1
    [ -n "$DRY" ] || verify_evidence "after the answer to the kill-argument" || exit 5
    judge "13c/15 kill-argument: the answered paper, judged again" \
"You are an area chair judging, for the first time, whether this paper answers a
hostile reviewer. This turn is that judging and nothing else.

KILL_ARGUMENT.json in this directory holds the reviewer's case
(details.attack_memo) and its points (details.decomposed_points). The paper has
been revised since they were judged. Judge every point again, from the current
submission.json and the evidence under runs/ alone: answered_by_current_text,
partially_answered or still_unresolved, with the evidence for the ruling. A
point the paper now only acknowledges as a limitation is partially_answered.
Keep each point's id, attack_claim and severity_if_unresolved as they are, and
add or drop none: the pipeline holds this judging to the attack's points and
severities.

Read nothing the author wrote about the revision -- leave refine-logs/ unread --
and do not edit submission.json, the paper or runs/; the pipeline compares
submission.json before and after this turn.

Rewrite KILL_ARGUMENT.json with the new rulings, and KILL_ARGUMENT.md to match;
the pipeline computes the verdict from the points." || exit 1
    if [ -z "$DRY" ]; then
      run "13c/15 what still stands against it (ours)" python3 "$KCHECK" "$KA" --held-to "$KDIR/attack.json"
      KV=$?
    fi
  fi
  case "$KV" in
    0|1) ;;
    2) echo "research: a critical point of the attack still stands against the paper (above)." >&2
       if [ "$BLOCKING" = 1 ]; then exit 6; fi
       say "^^ the kill-argument stands; NOT blocking (pilot mode)." ;;
    *) echo "research: step 13 has no usable verdict on the paper (above)." >&2
       if [ "$BLOCKING" = 1 ]; then exit 1; fi
       say "^^ no usable kill-argument verdict; NOT blocking (pilot mode)." ;;
  esac
  gated "13d/15 re-check shape after the answers" python3 "$ROOT/submission/scripts/check_submission_shape.py" "$W" || exit 5
fi

# ── 14 ─ ours: does every printed number exist? ─────────────────────────────
# Exit 1 is the paper's: numbers no result carries, or carries only as another
# metric -- the loop sends it back to step 11 with the list (exit 4). Exit 3 is
# the check's: it could not read the paper or run its checker, which no
# rewrite fixes -- the paper stops for a person (exit 1).
if want 14; then
  gated "14/15 cited-number check (ARIS evidence_check via ours)" \
        python3 "$ROOT/research/scripts/check_reproduction.py" "$W" --claims-only
  case $? in
    0) ;;
    1) echo "research: the paper cites numbers that are not in runs/results/." >&2; exit 4 ;;
    *) echo "research: the cited numbers could not be checked (above); a rewrite cannot fix that." >&2; exit 1 ;;
  esac
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
  # The protocol's fixed order lives in submit-paper.sh, which a paper the
  # owner brought goes through too. It prints "submitted: <id>" -- what the
  # heartbeat looks for -- and exits 0 without it when no cycle is open.
  "$ROOT/pipeline/submit-paper.sh" "$W" 2>&1 | tee -a "$LOG"
  [ "${PIPESTATUS[0]}" -eq 0 ] || exit 1
fi
say "done. artifacts in $W"
