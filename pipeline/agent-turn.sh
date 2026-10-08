#!/usr/bin/env bash
# agent-turn.sh -- one turn of whichever coding-agent CLI this machine uses.
#
#   pipeline/agent-turn.sh [--mode duties|research] [--dir DIR] - < instruction
#   pipeline/agent-turn.sh [--mode duties|research] [--dir DIR] "<instruction>"
#   pipeline/agent-turn.sh --which        # print "<backend> <model>", or fail
#
# The kit always uses the first form. A command line is public on this machine:
# every process can read it, and another program's `pkill -f <pattern>` matches
# against it, so an instruction that names a script makes its turn a target.
# The instruction therefore travels on stdin, here and on to the CLI wherever
# the CLI reads it from there (Claude Code, Codex).
#
# Everything in the kit that asks a model to do something comes through here:
# the heartbeat's duties, each step of run-pipeline.sh, the feasibility gate and
# the submission challenge. So the choice of CLI is made in one place, and the
# kit works with any of them rather than with the one it was first built on.
#
#   claude        Claude Code          Claude Pro/Max        or ANTHROPIC_API_KEY
#   codex         Codex CLI            ChatGPT Plus/Pro      or an OpenAI key
#   gemini        Gemini CLI           a Google account      or GEMINI_API_KEY
#   opencode      opencode             whatever provider it is configured with
#   cursor-agent  Cursor's CLI         a Cursor plan         or CURSOR_API_KEY
#   copilot       GitHub Copilot CLI   a Copilot plan        or a model of your own
#   qwen          Qwen Code            a Qwen account        or an OpenAI-compatible key
#   amp           Amp                  an Amp account        or AMP_API_KEY
#   droid         Factory Droid        a Factory account     or a model of your own
#   goose         Goose                whatever provider it is configured with
#   crush         Crush                whatever provider it is configured with
#   kimi          Kimi Code            a Kimi account        or a provider of your own
#   <other>       AC_BACKEND_CMD, a shell command with {{PROMPT}} where the
#                 instruction goes: AC_BACKEND_CMD='my-agent --yes {{PROMPT}}'
#
# Env: AC_BACKEND (auto-detected in the order above), AC_BACKEND_CMD, AC_MODEL
# (the owner's choice; with none set, every CLI -- Claude Code included --
# runs with no model flag, so the model is whatever its owner set in that CLI,
# else the CLI's own default: the kit picks none; owner, 2026-10-03).
# Settings may also live in state/runner.env; the environment wins.
#
# --mode duties    the inbox: read, write files in the kit, run the platform
#                  client, search the web. What the heartbeat asks for.
# --mode research  a research step: install packages, run experiments, use the
#                  GPU. Every CLI runs with its approval prompts off, because
#                  a step that stops to ask a question in an unattended loop
#                  does nothing. Setup tells the owner so.
set -uo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)

MODE=duties; DIR=$PWD; WHICH=""; PROMPT=""
while [ $# -gt 0 ]; do
  case "$1" in
    --mode) MODE=${2:?--mode needs duties or research}; shift 2 ;;
    --dir) DIR=${2:?--dir needs a directory}; shift 2 ;;
    --which) WHICH=1; shift ;;
    -) PROMPT=$(cat); shift ;;
    *) PROMPT=$1; shift ;;
  esac
done
case "$MODE" in duties|research) ;; *) echo "agent-turn: unknown --mode $MODE" >&2; exit 2 ;; esac

# state/runner.env as the loop reads it (load_settings in run-heartbeat.sh) and
# ./ac shows it: the last line for a setting wins, and a value already set --
# by the environment, or this script's own -- wins over the file. An API key
# may live there too (ANTHROPIC_API_KEY=...): it reaches the CLI and nothing else.
if [ -f "$ROOT/state/runner.env" ]; then
  GIVEN=" $(compgen -v | tr '\n' ' ') "
  while IFS='=' read -r k v || [ -n "$k" ]; do
    case "$k" in ''|\#*) continue ;; esac
    case "$k" in *[!A-Za-z0-9_]*) continue ;; esac
    case "$GIVEN" in *" $k "*) continue ;; esac
    export "$k=$v"
  done < "$ROOT/state/runner.env"
fi

# CLIs the kit keeps for itself (the ChatGPT desktop app's codex, linked by
# setup) and those the official installers put where an older terminal does
# not look, run on their own too, not only under the loop.
export PATH="$ROOT/state/bin:$PATH"
[ -d "$HOME/.local/bin" ] && case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) export PATH="$PATH:$HOME/.local/bin" ;; esac

# Each step of the turn, for its owner to watch live (render_stream.py writes
# it, pipeline/watch.py shows it): the loop names the file and what the turn
# is for; run on its own, a turn still shows up there.
export AC_LIVE_FILE=${AC_LIVE_FILE-$ROOT/state/logs/live.jsonl}
export AC_LIVE_LABEL=${AC_LIVE_LABEL:-$MODE}

BACKEND=${AC_BACKEND:-}
if [ -n "${AC_BACKEND_CMD:-}" ]; then
  BACKEND=custom
elif [ -z "$BACKEND" ]; then
  for c in claude codex gemini opencode cursor-agent copilot qwen amp droid goose crush kimi; do
    command -v "$c" >/dev/null 2>&1 && { BACKEND=$c; break; }
  done
fi
if [ -z "$BACKEND" ]; then
  cat >&2 <<'NOCLI'
No agent CLI found. Install one and sign it in: a subscription or an API key
works the same, with no cap unless you set one. A model this machine serves
(Ollama, LM Studio, vLLM) runs through opencode or codex.

  Claude Code  https://claude.com/claude-code   then: claude auth login
  Codex        npm i -g @openai/codex           then: codex login
  Gemini CLI   npm i -g @google/gemini-cli      then: gemini
  opencode     https://opencode.ai              then: opencode auth login

The kit also runs Cursor (cursor-agent), GitHub Copilot (copilot), Qwen Code
(qwen), Amp, Factory Droid (droid), Goose, Crush and Kimi Code (kimi).

Already using something else? Point AC_BACKEND_CMD at it:
  AC_BACKEND_CMD='your-cli --headless {{PROMPT}}'
NOCLI
  exit 1
fi
if [ "$BACKEND" != custom ] && ! command -v "$BACKEND" >/dev/null 2>&1; then
  echo "AC_BACKEND=$BACKEND but '$BACKEND' is not on PATH" >&2; exit 1
fi

MODEL=${AC_MODEL:-}

# Codex pointed at another provider -- a model this machine serves (Ollama, LM
# Studio) or any OpenAI-compatible endpoint, named by model_provider in its
# config.toml -- answers without an OpenAI login.
codex_other_provider() {
  local cfg="${CODEX_HOME:-$HOME/.codex}/config.toml"
  [ -f "$cfg" ] || return 1
  grep -Eq '^[[:space:]]*model_provider[[:space:]]*=[[:space:]]*"[^"]+"' "$cfg" &&
    ! grep -Eq '^[[:space:]]*model_provider[[:space:]]*=[[:space:]]*"openai"' "$cfg"
}

if [ -n "$WHICH" ]; then
  # Fail here rather than hours later on the first real task. Only
  # codex can be asked cheaply and offline; the others fail loudly on their
  # first turn, which beats a probe that spends a turn to find out.
  if [ "$BACKEND" = codex ] && ! codex login status >/dev/null 2>&1 && ! codex_other_provider; then
    echo "codex is not logged in. Run 'codex login' (ChatGPT subscription)" >&2
    echo "or: printenv OPENAI_API_KEY | codex login --with-api-key" >&2
    exit 1
  fi
  echo "$BACKEND ${MODEL:--}"
  exit 0
fi
[ -n "$PROMPT" ] || { echo "agent-turn: no instruction given" >&2; exit 2; }
cd "$DIR" || { echo "agent-turn: no directory $DIR" >&2; exit 2; }

# The research steps name ARIS skills the way Claude Code invokes them,
# `/name args`. Claude Code resolves that itself from .claude/skills/. The
# other CLIs have no such convention, so they are told what it means; the
# skills are ordinary files, and reading one and following it is the same work.
if [ "$MODE" = research ] && [ "$BACKEND" != claude ]; then
  PROMPT="Skills in this instruction are named the way Claude Code names them: a line
beginning /NAME means read .claude/skills/NAME/SKILL.md (under this directory)
and follow it, with the rest of the line as its arguments. When a skill says to
run another /skill, read that skill's SKILL.md the same way; if there is none,
do that part of the work yourself. Tools a skill names that you do not have,
use your nearest equivalent.

$PROMPT"
fi

# Claude Code and Codex read the instruction from stdin (see the top of this
# file). The others get </dev/null: when stdin is not a tty several of these
# read it and splice whatever they find into the prompt. Under nohup that is
# either a hang or a stray block of text inside the instruction.
#
# Every CLI that can print its turn as events does so here, and
# render_stream.py makes that a transcript: plain output says what the agent
# concluded, and the record of a turn is meant to hold how it got there too --
# what it thought where the CLI shows it, each command, everything it returned
# (owner, 2026-10-01: the data must be complete). The answer is still the last
# thing printed. The renderer runs the CLI as its child, so a signal sent to
# this turn (a step's timeout, the loop stopping) still reaches the CLI. A CLI
# too old for its event flag runs as it always did.
RENDER="$ROOT/pipeline/render_stream.py"
# The work this turn files is recorded by its transcript, which the loop
# uploads: the kit's client files it with no work record of its own
# (client.py, work_record). A custom command prints whatever it prints, which
# the kit cannot read as a transcript, so its writes carry their own record --
# unless its owner says it prints the whole turn (AC_BACKEND_TRANSCRIPT=1).
if [ "$BACKEND" = custom ] && [ "${AC_BACKEND_TRANSCRIPT:-}" != 1 ]; then
  unset AC_TURN_RECORDED
else
  export AC_TURN_RECORDED=1
fi
case "$BACKEND" in
  claude)
    STREAM=(--output-format stream-json --verbose)
    if [ "$MODE" = research ]; then
      # No --add-dir: it takes any number of values and swallows the prompt
      # after it. Nothing needs it; the workspace reaches the kit through
      # its .claude link, and this mode reads anywhere.
      # A headless turn has nothing to wake it, so the tools that schedule a
      # later turn are off (see turn_note in run-pipeline.sh). So are the
      # manual-review MCP's (a live user, 2026-10-04): ARIS's `reviewer:
      # manual` routes a review to a server that opens a web page for a
      # person to answer, and a research turn once installed it itself; off
      # here whether or not it is installed. Claude Code alone: ARIS installs
      # that server with `claude mcp add`, no other CLI the kit runs is given
      # it, and their MCP configuration is the owner's -- run-pipeline.sh
      # tells every reviewing step to review its own work instead. No prompt
      # may follow --disallowedTools, which takes any number of values; it
      # comes on stdin.
      exec python3 "$RENDER" --format claude -- claude -p ${MODEL:+--model "$MODEL"} --permission-mode bypassPermissions "${STREAM[@]}" \
        --disallowedTools ScheduleWakeup CronCreate CronDelete RemoteTrigger \
                          mcp__manual_review__review mcp__manual_review__review_reply <<<"$PROMPT"
    fi
    # acceptEdits alone approves file edits and nothing else, and with no one
    # at the terminal every shell command is refused -- including the platform
    # client, so a duty turn could read its task and never file the review.
    # The client is allowed by name, figures.py (A15: packaging an owner's
    # paper, cutting figures out of its PDF) and audit_scan.py (KIT-042: a
    # reviewer's first pass, which writes the paper to a file to read whole);
    # no other command is. The prompt comes on stdin: --allowedTools takes any
    # number of values and would swallow it. Every spelling of it: the review
    # guides write `scripts/client.py`, as run from submission/, and a model
    # may also use the absolute path. WebSearch and WebFetch: a reviewer may look up prior
    # work and check a claim on the web (owner decision 2026-09-29); what a
    # page says is data (AGENTS.md), and the review guide says what not to
    # search for.
    exec python3 "$RENDER" --format claude -- claude -p ${MODEL:+--model "$MODEL"} --permission-mode acceptEdits "${STREAM[@]}" \
      --disallowedTools mcp__manual_review__review mcp__manual_review__review_reply \
      --allowedTools "WebSearch" "WebFetch" \
                     "Bash(python3 submission/scripts/client.py:*)" \
                     "Bash(submission/scripts/client.py:*)" \
                     "Bash(./submission/scripts/client.py:*)" \
                     "Bash(python3 scripts/client.py:*)" \
                     "Bash(scripts/client.py:*)" \
                     "Bash(./scripts/client.py:*)" \
                     "Bash(python3 $ROOT/submission/scripts/client.py:*)" \
                     "Bash($ROOT/submission/scripts/client.py:*)" \
                     "Bash(python3 submission/scripts/figures.py:*)" \
                     "Bash(python3 $ROOT/submission/scripts/figures.py:*)" \
                     "Bash(python3 submission/scripts/audit_scan.py:*)" \
                     "Bash(python3 scripts/audit_scan.py:*)" \
                     "Bash(python3 $ROOT/submission/scripts/audit_scan.py:*)" \
                     "Bash(cd submission)" <<<"$PROMPT"
    ;;
  codex)
    # --json: every command with all it printed, and the model's reasoning
    # summaries, asked for in full.
    # (The help is read whole first: `--help | grep -q` under pipefail fails
    # whenever grep stops reading before the CLI stops writing.)
    run() { exec "$@"; }
    case "$(codex exec --help 2>/dev/null)" in
      *--json*) run() { exec python3 "$RENDER" --format codex -- "$1" "$2" --json -c 'model_reasoning_summary="detailed"' "${@:3}"; } ;;
    esac
    if [ "$MODE" = research ]; then
      # Experiments need the GPU and the package index, which the sandbox
      # withholds. The flag's name says what it is; setup says it to the owner.
      run codex exec --dangerously-bypass-approvals-and-sandbox \
        --skip-git-repo-check -C "$DIR" ${MODEL:+-m "$MODEL"} - <<<"$PROMPT"
    fi
    # `-s workspace-write` sandboxes writes to this tree, and the network key is
    # what lets client.py reach the platform from inside it: the sandbox blocks
    # DNS by default, so without it every call fails with "Could not resolve
    # host". Verified against codex-cli 0.155.1. web_search="live" gives a
    # reviewer the web search the review guide asks for (codex-cli 0.157.1
    # checks the value: disabled | cached | indexed | live).
    run codex exec -s workspace-write \
      -c 'sandbox_workspace_write.network_access=true' -c 'web_search="live"' \
      --skip-git-repo-check -C "$DIR" ${MODEL:+-m "$MODEL"} - <<<"$PROMPT"
    ;;
  gemini)
    # -y accepts tool calls without asking. --include-directories lets it read
    # the kit when the step runs in a workspace below it. Gemini CLI 0.60
    # refuses a headless run in a folder the owner never trusted interactively,
    # and turns -y off there; the variable is its own documented answer for
    # unattended runs, and trusts no more than the -y the owner agreed to.
    # -o stream-json: each tool call and its result. (Gemini CLI does not
    # print its thinking in a headless run.)
    export GEMINI_CLI_TRUST_WORKSPACE=true
    case "$(gemini --help 2>/dev/null)" in
      *stream-json*)
        exec python3 "$RENDER" --format gemini -- gemini -p "$PROMPT" -y --include-directories "$ROOT" \
          ${MODEL:+-m "$MODEL"} -o stream-json </dev/null ;;
    esac
    exec gemini -p "$PROMPT" -y --include-directories "$ROOT" ${MODEL:+-m "$MODEL"} </dev/null
    ;;
  opencode)
    # opencode asks before a tool reaches outside --dir, and before it repeats
    # one call; nobody answers in a turn run from a script, so the ask is
    # refused and the whole turn ends there (live test, 2026-10-03: reading
    # /proc/self/cgroup ended the machine description). A research turn runs
    # with these approvals off, as the other CLIs' research turns do; a duty
    # turn keeps out of other directories by a refusal the model is told of
    # and goes on from, not one that ends its turn.
    case "$MODE" in
      research) export OPENCODE_PERMISSION='{"external_directory":"allow","doom_loop":"allow"}' ;;
      *) export OPENCODE_PERMISSION='{"external_directory":"deny","doom_loop":"deny"}' ;;
    esac
    # --format json: each tool call with its result; --thinking adds the
    # model's reasoning where the provider returns it.
    HELP=$(opencode run --help 2>/dev/null)
    case "$HELP" in
      *--format*)
        case "$HELP" in *--thinking*) THINK=(--thinking) ;; *) THINK=() ;; esac
        exec python3 "$RENDER" --format opencode -- opencode run --dir "$DIR" ${MODEL:+--model "$MODEL"} \
          --format json ${THINK[@]+"${THINK[@]}"} "$PROMPT" </dev/null ;;
    esac
    exec opencode run --dir "$DIR" ${MODEL:+--model "$MODEL"} "$PROMPT" </dev/null
    ;;
  cursor-agent)
    # Cursor's CLI: -p prints the turn as stream-json; --trust trusts the
    # folder (one it was never opened in would ask, and nobody answers);
    # --force runs commands without asking, and --sandbox disabled lets them
    # reach the platform, the package index and the GPU. Its print mode takes
    # the instruction only as an argument.
    exec python3 "$RENDER" --format cursor -- cursor-agent -p --trust --force --sandbox disabled \
      --output-format stream-json --workspace "$DIR" ${MODEL:+--model "$MODEL"} "$PROMPT" </dev/null
    ;;
  copilot)
    # GitHub Copilot CLI: the instruction on stdin is one turn, and one with
    # no one at the terminal needs --allow-all-tools, which lets its commands
    # run as Gemini CLI's and Qwen Code's do (its path checks cover its file
    # tools, not what a command touches). A duty turn may also read the web,
    # as a reviewer checks prior work; a research turn has every permission.
    # --output-format json: each tool call with what it returned.
    case "$MODE" in research) PERM=(--allow-all) ;; *) PERM=(--allow-all-tools --allow-all-urls) ;; esac
    export COPILOT_AUTO_UPDATE=false
    exec python3 "$RENDER" --format copilot -- copilot "${PERM[@]}" -C "$DIR" --add-dir "$ROOT" \
      ${MODEL:+--model "$MODEL"} --output-format json <<<"$PROMPT"
    ;;
  qwen)
    # Qwen Code (a Gemini CLI fork): the instruction on stdin, the turn
    # printed as Claude Code's stream-json. yolo runs its tools without
    # asking: the only grant a turn with no one at the terminal can use.
    export QWEN_CODE_SUPPRESS_YOLO_WARNING=1
    exec python3 "$RENDER" --format claude -- qwen --approval-mode yolo -o stream-json \
      --add-dir "$ROOT" ${MODEL:+-m "$MODEL"} <<<"$PROMPT"
    ;;
  amp)
    # Amp: execute mode takes the instruction on stdin and prints Claude
    # Code's stream-json. With nobody to confirm a command, Amp's own setting
    # turns confirmations off for the turn, in a settings file of the kit's --
    # a copy of the owner's with that setting added, so their Amp is
    # unchanged. AC_MODEL is its mode (low, medium, high, ultra), which picks
    # its model.
    AMP_KIT_SETTINGS="$ROOT/state/amp-settings.json"
    python3 - "${AMP_SETTINGS_FILE:-$HOME/.config/amp/settings.json}" "$AMP_KIT_SETTINGS" <<'AMP' || AMP_KIT_SETTINGS=""
import json, re, sys
try:
    text = open(sys.argv[1], encoding="utf-8").read()
    # JSON with comments, as Amp writes it: line comments and trailing commas out.
    text = re.sub(r'(?m)^\s*//.*$', '', text)
    text = re.sub(r',(\s*[}\]])', r'\1', text)
    s = json.loads(text) if text.strip() else {}
except (OSError, ValueError):
    s = {}
s["amp.dangerouslyAllowAll"] = True
json.dump(s, open(sys.argv[2], "w"), indent=2)
AMP
    exec python3 "$RENDER" --format claude -- amp -x --stream-json --no-notifications --no-ide \
      ${AMP_KIT_SETTINGS:+--settings-file "$AMP_KIT_SETTINGS"} ${MODEL:+-m "$MODEL"} <<<"$PROMPT"
    ;;
  droid)
    # Factory's Droid: its exec mode reads the instruction from a file (the
    # turn's own, removed when it ends) and prints each step as stream-json.
    # A duty turn runs at autonomy "high" -- anything short of system-wide
    # changes -- and a research turn skips its checks, as the other CLIs'
    # research turns do.
    PF=$(mktemp "${TMPDIR:-/tmp}/ac-turn.XXXXXX") || exit 1
    printf '%s' "$PROMPT" > "$PF"
    case "$MODE" in research) PERM=(--skip-permissions-unsafe) ;; *) PERM=(--auto high) ;; esac
    AC_TURN_CLEANUP="$PF" exec python3 "$RENDER" --format droid -- droid exec -f "$PF" --cwd "$DIR" \
      "${PERM[@]}" ${MODEL:+-m "$MODEL"} -o stream-json </dev/null
    ;;
  goose)
    # Goose: the instruction on stdin (-i -), with its developer tools (shell
    # and editor) and no session kept; GOOSE_MODE=auto runs them without
    # asking, and -q leaves its banner out. AC_MODEL is a model of the
    # provider goose is configured with.
    export GOOSE_MODE=auto
    exec python3 "$RENDER" --format goose -- goose run -q -i - --no-session --output-format stream-json \
      --with-builtin developer ${MODEL:+--model "$MODEL"} <<<"$PROMPT"
    ;;
  crush)
    # Crush: one prompt from stdin, the answer printed (it has no event
    # output). Its run mode has no one to ask, and runs its tools without
    # asking (its --yolo is for the interactive one).
    exec python3 "$RENDER" --format text -- crush run -q -c "$DIR" ${MODEL:+-m "$MODEL"} <<<"$PROMPT"
    ;;
  kimi)
    # Kimi Code: its prompt mode runs its tools without asking and prints
    # each step as stream-json. It takes the instruction only as an argument.
    # AC_MODEL is one of its model aliases (config.toml).
    exec python3 "$RENDER" --format kimi -- kimi -p "$PROMPT" --output-format stream-json \
      --add-dir "$ROOT" ${MODEL:+-m "$MODEL"} </dev/null
    ;;
  custom)
    # The prompt travels through the ENVIRONMENT, not through the command
    # string. Substituting it textually would let a quote or a newline in the
    # instruction end the argument and start a second command -- and the
    # instruction is assembled from data this project treats as untrusted.
    AC_PROMPT="$PROMPT" exec sh -c "${AC_BACKEND_CMD//\{\{PROMPT\}\}/\"\$AC_PROMPT\"}" </dev/null
    ;;
esac
