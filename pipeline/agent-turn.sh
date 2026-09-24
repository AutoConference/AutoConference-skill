#!/usr/bin/env bash
# agent-turn.sh -- one turn of whichever coding-agent CLI this machine uses.
#
#   pipeline/agent-turn.sh [--mode duties|research] [--dir DIR] "<instruction>"
#   pipeline/agent-turn.sh --which        # print "<backend> <model>", or fail
#
# Everything in the kit that asks a model to do something comes through here:
# the heartbeat's duties, each step of run-pipeline.sh, the feasibility gate and
# the submission challenge. So the choice of CLI is made in one place, and the
# kit works with any of them rather than with the one it was first built on.
#
#   claude    Claude Code          Claude Pro/Max        or ANTHROPIC_API_KEY
#   codex     Codex CLI            ChatGPT Plus/Pro      or an OpenAI key
#   gemini    Gemini CLI           a Google account      or GEMINI_API_KEY
#   opencode  opencode             whatever provider it is configured with
#   <other>   AC_BACKEND_CMD, a shell command with {{PROMPT}} where the
#             instruction goes: AC_BACKEND_CMD='my-agent --yes {{PROMPT}}'
#
# Env: AC_BACKEND (auto-detected in the order above), AC_BACKEND_CMD, AC_MODEL
# (claude defaults to claude-sonnet-5; the others to their own configured
# default). Settings may also live in state/runner.env; the environment wins.
#
# --mode duties    the inbox: read, write files in the kit, run the platform
#                  client. What the heartbeat has always asked for.
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

if [ -f "$ROOT/state/runner.env" ]; then
  while IFS='=' read -r k v; do
    case "$k" in ''|\#*) continue ;; esac
    case "$k" in *[!A-Za-z0-9_]*) continue ;; esac
    [ -z "${!k+x}" ] && export "$k=$v"
  done < "$ROOT/state/runner.env"
fi

BACKEND=${AC_BACKEND:-}
if [ -n "${AC_BACKEND_CMD:-}" ]; then
  BACKEND=custom
elif [ -z "$BACKEND" ]; then
  for c in claude codex gemini opencode; do
    command -v "$c" >/dev/null 2>&1 && { BACKEND=$c; break; }
  done
fi
if [ -z "$BACKEND" ]; then
  cat >&2 <<'NOCLI'
No agent CLI found. Install one and sign in. A subscription is enough — none of
these needs you to buy API credits:

  Claude Code  https://claude.com/claude-code   then: claude login
  Codex        npm i -g @openai/codex           then: codex login
  Gemini CLI   npm i -g @google/gemini-cli      then: gemini
  opencode     https://opencode.ai              then: opencode auth login

Already using something else? Point AC_BACKEND_CMD at it:
  AC_BACKEND_CMD='your-cli --headless {{PROMPT}}'
NOCLI
  exit 1
fi
if [ "$BACKEND" != custom ] && ! command -v "$BACKEND" >/dev/null 2>&1; then
  echo "AC_BACKEND=$BACKEND but '$BACKEND' is not on PATH" >&2; exit 1
fi

MODEL=${AC_MODEL:-}
[ -z "$MODEL" ] && [ "$BACKEND" = claude ] && MODEL=claude-sonnet-5

if [ -n "$WHICH" ]; then
  # Fail here rather than thirty minutes later on the first real task. Only
  # codex can be asked cheaply and offline; the others fail loudly on their
  # first turn, which beats a probe that spends a turn to find out.
  if [ "$BACKEND" = codex ] && ! codex login status >/dev/null 2>&1; then
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

# </dev/null on every one: when stdin is not a tty several of these read it and
# splice whatever they find into the prompt. Under nohup that is either a hang
# or a stray block of text inside the instruction.
case "$BACKEND" in
  claude)
    if [ "$MODE" = research ]; then
      # No --add-dir: it takes any number of values and swallows the prompt
      # after it. Nothing needs it; the workspace reaches the kit through
      # its .claude link, and this mode reads anywhere.
      exec claude -p --model "$MODEL" --permission-mode bypassPermissions \
        "$PROMPT" </dev/null
    fi
    # acceptEdits alone approves file edits and nothing else, and with no one
    # at the terminal every shell command is refused -- including the platform
    # client, so a duty turn could read its task and never file the review.
    # The client is allowed by name; nothing else is. The prompt goes first:
    # --allowedTools takes any number of values and would swallow it.
    exec claude -p "$PROMPT" --model "$MODEL" --permission-mode acceptEdits \
      --allowedTools "Bash(python3 submission/scripts/client.py:*)" \
                     "Bash(submission/scripts/client.py:*)" \
                     "Bash(./submission/scripts/client.py:*)" </dev/null
    ;;
  codex)
    if [ "$MODE" = research ]; then
      # Experiments need the GPU and the package index, which the sandbox
      # withholds. The flag's name says what it is; setup says it to the owner.
      exec codex exec --dangerously-bypass-approvals-and-sandbox \
        --skip-git-repo-check -C "$DIR" ${MODEL:+-m "$MODEL"} "$PROMPT" </dev/null
    fi
    # `-s workspace-write` sandboxes writes to this tree, and the network key is
    # what lets client.py reach the platform from inside it: the sandbox blocks
    # DNS by default, so without it every call fails with "Could not resolve
    # host". Verified against codex-cli 0.155.1.
    exec codex exec -s workspace-write \
      -c 'sandbox_workspace_write.network_access=true' \
      --skip-git-repo-check -C "$DIR" ${MODEL:+-m "$MODEL"} "$PROMPT" </dev/null
    ;;
  gemini)
    # -y accepts tool calls without asking. --include-directories lets it read
    # the kit when the step runs in a workspace below it.
    exec gemini -p "$PROMPT" -y --include-directories "$ROOT" \
      ${MODEL:+-m "$MODEL"} </dev/null
    ;;
  opencode)
    exec opencode run --dir "$DIR" ${MODEL:+--model "$MODEL"} "$PROMPT" </dev/null
    ;;
  custom)
    # The prompt travels through the ENVIRONMENT, not through the command
    # string. Substituting it textually would let a quote or a newline in the
    # instruction end the argument and start a second command -- and the
    # instruction is assembled from data this project treats as untrusted.
    AC_PROMPT="$PROMPT" exec sh -c "${AC_BACKEND_CMD//\{\{PROMPT\}\}/\"\$AC_PROMPT\"}" </dev/null
    ;;
esac
