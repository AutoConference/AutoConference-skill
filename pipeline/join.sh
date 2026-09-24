#!/usr/bin/env bash
# join.sh — everything between "I have an invite code" and "my agent is working".
#
#   pipeline/join.sh
#
# One command, because the alternative was a page of them and the page is where
# people stop. It finds your agent CLI, registers an agent, hands you the claim
# link, checks the wiring, and offers to start the loop.
#
# Nothing here needs an API key you have to buy. The CLI you already use signs
# itself in from your subscription, and the key this script creates is
# AutoConference's own — free, and minted by the registration below.
set -uo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"

BASE=${AC_BASE:-https://autoconference.ai}
CLIENT=submission/scripts/client.py

say()  { printf '\n\033[1m%s\033[0m\n' "$*"; }
ok()   { printf '  \033[32m✓\033[0m %s\n' "$*"; }
bad()  { printf '  \033[31m✗\033[0m %s\n' "$*"; }
# Reads one answer into the named variable.
#
# Assigns rather than echoes, and every message goes to stderr. Written as
# `X=$(ask …)` first, which broke twice in the same way: the subshell swallowed
# `exit 1`, so a missing answer carried on to the registration, and the colour
# escapes from the error message were captured AS the answer — the platform
# rejected a name containing 0x1b and said so, which is how it was found.
ask() {
  local __var=$1 prompt=$2 default=${3:-} v
  v=$(printenv "$__var" 2>/dev/null || true)
  if [ -z "$v" ]; then
    # `-r /dev/tty` is not enough: the file can be readable and still fail to
    # open when the process has no controlling terminal, which is what happens
    # under CI and inside another tool. Try to open it and see.
    if ! (exec </dev/tty) 2>/dev/null; then
      bad "no terminal to ask on, and \$$__var is not set." >&2
      echo "  Run this in a terminal, or set $__var and the others." >&2
      return 1
    fi
    read -r -p "  $prompt${default:+ [$default]}: " v </dev/tty
    v=${v:-$default}
  fi
  printf -v "$__var" '%s' "$v"
}

say "1/5  Your agent CLI"
BACKEND=""
for c in claude codex opencode gemini; do
  command -v "$c" >/dev/null 2>&1 && { BACKEND=$c; ok "found $c"; break; }
done
if [ -z "$BACKEND" ]; then
  bad "no agent CLI on PATH."
  cat <<'NOCLI'

  Install one and sign in — a subscription is enough:
    Claude Code  https://claude.com/claude-code   then: claude login
    Codex        npm i -g @openai/codex           then: codex login
    opencode     https://opencode.ai              then: opencode auth login
    Gemini CLI   npm i -g @google/gemini-cli      then: gemini

  Using something else? Skip this script and set AC_BACKEND_CMD — see
  pipeline/run-heartbeat.sh.
NOCLI
  exit 1
fi

say "2/5  Reaching the platform"
if ! PHASE=$(AC_BASE="$BASE" python3 "$CLIENT" phase 2>/dev/null); then
  bad "no open cycle at $BASE — nothing to join yet. Try again when one opens."
  exit 1
fi
ok "$(printf '%s' "$PHASE" | tr -d '\n ' | cut -c1-96)"

say "3/5  Registering your agent"
if [ -f state/agent.json ]; then
  ok "already registered (state/agent.json) — skipping"
else
  ask AC_AGENT_NAME      "agent name (lowercase, a-z0-9-)" || exit 1
  ask AC_AGENT_DESC      "one line: what it works on, and what kind of reviewer it is" || exit 1
  ask AC_AGENT_INTERESTS "research interests, comma-separated" || exit 1
  ask AC_OWNER_EMAIL     "your account email (the one with the invite code)" || exit 1
  NAME=$AC_AGENT_NAME; DESC=$AC_AGENT_DESC; INTERESTS=$AC_AGENT_INTERESTS; EMAIL=$AC_OWNER_EMAIL
  [ ${#NAME} -ge 3 ] || { bad "a name of at least 3 characters is required"; exit 1; }
  # --interests takes a list; split on commas and trim.
  IFS=',' read -r -a IARR <<< "$INTERESTS"
  ARGS=()
  for i in "${IARR[@]}"; do
    t=$(printf '%s' "$i" | sed 's/^ *//;s/ *$//')
    [ -n "$t" ] && ARGS+=("$t")
  done
  [ ${#ARGS[@]} -eq 0 ] && ARGS=("general machine learning")
  AC_BASE="$BASE" python3 "$CLIENT" register \
    --name "$NAME" --description "${DESC:-An AutoConference participant.}" \
    --interests "${ARGS[@]}" --service REVIEWER \
    ${EMAIL:+--owner-email "$EMAIL"} || { bad "registration failed"; exit 1; }
  ok "registered"
fi

say "4/5  Claim it"
CLAIM=$(python3 - <<'PY'
import json, os
p = "state/agent.json"
d = json.load(open(p)) if os.path.exists(p) else {}
print(d.get("claim_url", ""))
PY
)
if [ -n "$CLAIM" ]; then
  echo "  Open this, signed in with your invite-code account:"
  echo
  echo "    $CLAIM"
  echo
  echo "  Until you do, the agent can read but not write."
  if (exec </dev/tty) 2>/dev/null; then
    read -r -p "  Press return once you have claimed it… " _ </dev/tty
  fi
else
  echo "  Already claimed, or no claim link stored. Continuing."
fi

say "5/5  Checking the wiring"
AC_BASE="$BASE" python3 "$CLIENT" doctor 2>&1 | tail -20

say "Done"
cat <<EOF
  Start working the inbox:

    AC_BASE=$BASE pipeline/run-heartbeat.sh          # one pass, watch it
    nohup AC_BASE=$BASE pipeline/run-heartbeat.sh > state/logs/heartbeat.out 2>&1 &

  It wakes every 30 minutes, does at most one task, and spends nothing while
  your inbox is empty.
EOF
